---
name: add-job-source
description: Add a new job source adapter (API, RSS, ATS board type) to Hirenza discovery, with tests. Use when the user wants jobs from a new site/feed or a new ATS vendor.
---

1. Check compliance first: official API, public ATS/job-board feed, RSS, or the user's own email only.
   If the site forbids automation (LinkedIn, Naukri, Instahyre, Foundit…), do NOT scrape — suggest its
   alert emails (extend `sources/email_alerts.py` PROVIDERS) or an aggregator API instead.
2. Create `backend/app/agents/discovery/sources/<name>.py` with a `SourceAdapter` subclass:
   - `key`, `name`, `kind` (ats|api|rss|email), `min_interval_minutes` set to respect the source's rate limits.
   - `is_configured()` returns False when required env keys are missing (add them to `core/config.py`
     as `SecretStr | None` and to `.env.example` + `.github/workflows/hunt.yml` env).
   - `fetch(client, ctx) -> list[Batch]`; map fields into `RawJob`. Use `html_to_text`, `parse_datetime`.
   - Set `Batch(authoritative=True, scope=...)` only if the response is the COMPLETE open-job list for that scope
     (enables closed-job detection).
   - Return `Batch([], error=...)` instead of raising for partial failures.
3. Register it in `sources/__init__.py` `ADAPTERS`.
4. Add a respx-mocked parse test in `backend/tests/test_sources.py`.
5. Run `.venv/bin/pytest -q` and `.venv/bin/ruff check app tests`, then a live check:
   `python -m app.cli discover --force --only <key>`.
