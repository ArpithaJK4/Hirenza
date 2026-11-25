"""Confidentiality guardrails. These are HARD blocks, not preferences.

1. Never apply to the candidate's current employer.
2. Never contact current-employer employees.
3. Never post or act on LinkedIn (enforced by design: no LinkedIn write adapter exists).
"""
import re

from app.core.config import get_settings

_SUFFIXES = re.compile(
    r"\b(pvt|private|ltd|limited|llc|inc|incorporated|corp|corporation|co|technologies|technology|"
    r"tech|solutions|solution|software|systems|labs|gmbh|bv|plc)\b"
)


def normalize_company(name: str | None) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = _SUFFIXES.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def _employer_keys() -> set[str]:
    return {k for k in (normalize_company(n) for n in get_settings().current_employer_names) if k}


def _employer_domains() -> set[str]:
    return {d.lower().lstrip("@").strip() for d in get_settings().current_employer_domains if d.strip()}


def is_current_employer(company_name: str | None = None, *, url_or_email: str | None = None) -> bool:
    keys = _employer_keys()
    if company_name and keys:
        norm = normalize_company(company_name)
        squashed = norm.replace(" ", "")
        for k in keys:
            if norm == k or squashed == k.replace(" ", "") or re.search(rf"\b{re.escape(k)}\b", norm):
                return True
    if url_or_email:
        target = url_or_email.lower()
        host = target.split("@")[-1] if "@" in target and "://" not in target else \
            re.sub(r"^[a-z]+://", "", target).split("/")[0]
        for d in _employer_domains():
            if host == d or host.endswith("." + d):
                return True
    return False


def text_mentions_current_employer(text: str | None) -> bool:
    """Used to drop jobs posted by recruiters/consultancies *for* the current employer."""
    if not text:
        return False
    norm = normalize_company(text)
    return any(re.search(rf"\b{re.escape(k)}\b", norm) for k in _employer_keys())
