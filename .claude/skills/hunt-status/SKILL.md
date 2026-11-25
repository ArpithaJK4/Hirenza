---
name: hunt-status
description: Check how the Hirenza job hunter is doing — source health, latest pipeline runs, top new matches and skill gaps. Use when the user asks "how is it going", "any new jobs", "is the hunter working".
---

Run from `backend/` with the user's `.env` loaded (DATABASE_URL points at Neon):

1. `set -a; source ../.env; set +a`
2. `.venv/bin/python -m app.cli sources` — flag any source with status failed / consecutive failures.
3. `.venv/bin/python -m app.cli top --fresh --limit 10` — best jobs from the last 24h.
4. `.venv/bin/python -m app.cli gaps | head -12` — skill-gap radar.
5. Optionally `gh run list --workflow hunt.yml --limit 5` to confirm the schedule is running.

Report briefly: is it running, how many fresh high matches, top 3 jobs with links, top 3 skill gaps,
and any broken source with the likely fix. Never print secrets from .env.
