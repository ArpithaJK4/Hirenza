"""LLM provider abstraction with caching and a daily call budget.

Token strategy:
- The rule engine does the bulk work for free; the LLM only sees the top-N jobs.
- Every response is cached by hash(model, purpose, prompt) in `llm_cache` — identical work is never paid twice.
- A daily call limit caps spend; when exceeded (or no provider), callers fall back to templates.
- Prompts contain only the facts needed (trimmed JD + resume), never whole documents twice.
"""
import hashlib
import json
import logging
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import utcnow
from app.models import LLMCache

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    pass


def provider_name() -> str:
    s = get_settings()
    if s.llm_provider == "anthropic" and s.anthropic_api_key:
        return "anthropic"
    if s.llm_provider == "ollama":
        return "ollama"
    return "none"


def available() -> bool:
    return provider_name() != "none"


def _model() -> str:
    s = get_settings()
    return s.llm_model if provider_name() == "anthropic" else s.ollama_model


def _calls_today(db: Session) -> int:
    return db.scalar(select(func.count(LLMCache.id)).where(
        LLMCache.created_at >= utcnow() - timedelta(days=1))) or 0


def _anthropic_json(system: str, prompt: str, schema: dict, effort: str, max_tokens: int) -> tuple[dict, int, int]:
    import anthropic

    s = get_settings()
    client = anthropic.Anthropic(api_key=s.anthropic_api_key.get_secret_value(), max_retries=2, timeout=120)
    try:
        resp = client.beta.messages.create(
            model=s.llm_model,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.RateLimitError as e:
        raise LLMUnavailable("rate limited") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"API error {e.status_code}") from e
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable("network error") from e
    if resp.stop_reason == "refusal":
        raise LLMUnavailable("model declined")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text), resp.usage.input_tokens, resp.usage.output_tokens


def _ollama_json(system: str, prompt: str, schema: dict, max_tokens: int) -> tuple[dict, int, int]:
    s = get_settings()
    try:
        r = httpx.post(f"{s.ollama_base_url}/api/chat", timeout=300, json={
            "model": s.ollama_model, "stream": False, "format": schema,
            "options": {"num_predict": max_tokens},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        r.raise_for_status()
        data = r.json()
        return json.loads(data["message"]["content"]), data.get("prompt_eval_count", 0), data.get("eval_count", 0)
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise LLMUnavailable(f"ollama: {type(e).__name__}") from e


def complete_json(db: Session, *, purpose: str, system: str, prompt: str, schema: dict,
                  effort: str = "low", max_tokens: int = 4000) -> dict:
    """Return a schema-valid dict, from cache when possible. Raises LLMUnavailable on any failure."""
    prov = provider_name()
    if prov == "none":
        raise LLMUnavailable("no LLM provider configured")
    model = _model()
    key = hashlib.sha256(json.dumps([model, purpose, system, prompt, schema], sort_keys=True).encode()).hexdigest()
    cached = db.scalar(select(LLMCache).where(LLMCache.key == key))
    if cached:
        return cached.response
    if _calls_today(db) >= get_settings().llm_daily_call_limit:
        raise LLMUnavailable("daily LLM call limit reached")
    if prov == "anthropic":
        data, tin, tout = _anthropic_json(system, prompt, schema, effort, max_tokens)
    else:
        data, tin, tout = _ollama_json(system, prompt, schema, max_tokens)
    db.add(LLMCache(key=key, purpose=purpose, model=model, response=data, input_tokens=tin, output_tokens=tout))
    db.flush()
    return data


def usage_summary(db: Session, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(select(LLMCache.purpose, func.count(), func.sum(LLMCache.input_tokens),
                             func.sum(LLMCache.output_tokens))
                      .where(LLMCache.created_at >= since).group_by(LLMCache.purpose)).all()
    return {"provider": provider_name(), "model": _model() if available() else None,
            "by_purpose": [{"purpose": p, "calls": c, "input_tokens": i or 0, "output_tokens": o or 0}
                           for p, c, i, o in rows]}
