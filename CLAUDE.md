# Hirenza — AI Job Hunter

Personal job-search platform: discover → match → (prepare → human approve → submit) → track.
Plan: docs/PLAN.md · Architecture: docs/ARCHITECTURE.md (read only the section you need).

## HARD guardrails (never weaken, never make optional)
1. **No LinkedIn posting/automation.** LinkedIn is read-only via alert emails. No LinkedIn write adapter may exist.
2. **Never contact current-employer employees** and **never apply to current-employer jobs.**
   Use `app.guardrails.is_current_employer()` in every agent that touches companies/people
   (discovery, matching, application, outreach, referral). Employer list comes from env
   `CURRENT_EMPLOYER_NAMES` / `CURRENT_EMPLOYER_DOMAINS` — never hardcode it in the repo.
3. **Human approval** before any application submit or message send. The ONLY exception is auto-apply
   (user-enabled `AUTO_APPLY_ENABLED` rule = standing approval) on PUBLIC company ATS forms
   (Greenhouse/Lever/Ashby): never on login-based sites (LinkedIn/Naukri/Indeed), never past a CAPTCHA,
   never guessing an answer (unknown required question → manual review), daily cap + pause switch, and
   "submitted" only after a confirmation page. Never fabricate jobs, contacts, confirmations or outcomes.
4. Only compliant sources: official APIs, public ATS feeds, RSS, the user's own email. No scraping
   behind auth, no CAPTCHA/rate-limit bypass.
5. Secrets only via env (`SecretStr`). Repo may be public: no personal contact data in code/data files.

## Commands (run from backend/, venv at backend/.venv)
- Tests: `.venv/bin/pytest -q` · Lint: `.venv/bin/ruff check app tests alembic`
- New migration: `SECRET_KEY=x DATABASE_URL=sqlite:////tmp/gen.db .venv/bin/alembic upgrade head && ... alembic revision --autogenerate -m "<msg>" --rev-id 000N`
- CLI: `python -m app.cli {bootstrap|create-user|pipeline [--force] [--only a,b]|top|gaps|sources}`
- API dev: `uvicorn app.main:app --reload` → /docs

## Layout
backend/app: core/ (config, db, security) · models/ · schemas/ · api/routes/ · guardrails/ ·
agents/discovery/sources/ (one adapter per source, registered in sources/__init__.py) ·
agents/matching/ (skills vocab, scorer, suspicious, service) · notifications/ · workers/pipeline.py
(orchestrator used by CLI, Celery and API). Zero-cost runtime = .github/workflows/hunt.yml + Neon Postgres.

## Conventions
- A failing source/provider must never stop the pipeline (catch per source, record, continue).
- DB access in loops must be batched (Neon is remote: ~30 ms per round-trip).
- LLM calls (phase 2+) only on jobs already ranked high by the rule scorer; cache results.
- Every phase: models → migration → service → API → tests → docs/PLAN.md status.

## Token-saving tips for Claude
- Don't read data/companies.yaml or alembic/versions/* in full; grep them.
- Use `pytest -q` and `tail` output. Prefer the project skills: /add-job-source, /hunt-status, /build-phase.
