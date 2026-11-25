# Hirenza — AI Job Hunter

Finds fresh Python / DevOps / Platform / SRE / DevSecOps / Cloud jobs (India first, then worldwide),
scores them against your profile, filters ghost/scam listings and emails you the best ones within
~15 minutes of posting. Later phases add tailored resumes, a review queue, outreach drafts, a Kanban
tracker and interview prep — always with **human approval** before anything is submitted or sent.

- Plan & phases: [docs/PLAN.md](docs/PLAN.md) · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Hard guardrails: no LinkedIn posting, never contact or apply to your current employer (see [CLAUDE.md](CLAUDE.md)).

## What it does

| Agent | Features |
|---|---|
| 1 · Discovery | 70+ verified Greenhouse/Lever/Ashby boards, Remote OK, WWR, Adzuna*, JSearch*, LinkedIn & Naukri alert emails* · dedupe · closed-job detection · per-source rate budgets |
| 2 · Matching | rule scorer (title, skills, experience, location/visa realism, freshness, salary) → optional LLM re-rank of top-N (cached) · explanations · missing skills · ghost/scam filter · learned boosts |
| 3 · Application | resume upload/parsing · tailored resume per job (reordered, never invented) with A/B variants · cover letter · ATS PDF · Greenhouse form questions · review queue · approve/reject · **local autofill that never clicks submit** · duplicate block · confirmation tracking |
| 4 · Outreach | referral finder (LinkedIn Connections.csv) · recruiter/hiring-manager drafts (LinkedIn note ≤300 chars, email, referral ask, follow-up) · approve → send email / copy LinkedIn text · hiring-signal radar (funding news) · proof-of-work Trivy scan |
| 5 · Tracking | Kanban tracker · interviews + auto prep pack · offers · follow-up reminders · analytics by source / role / resume variant / company · "learn from outcomes" ranking boosts |
| Platform | JWT auth, argon2, rate limits, audit log, email/Telegram alerts, 10-page React dashboard, Alembic migrations, CI (ruff, pytest, Postgres, frontend build, Trivy), GitHub Actions scheduler |

Hard rules: no LinkedIn posting/automation · never apply to or contact your current employer · nothing is submitted or sent without your approval.

## Run on your laptop (no server, no accounts) — recommended

```bash
./scripts/start-local.sh
```
First run creates `.env` (local SQLite database), installs everything, asks for a dashboard login, then
starts the API, the 15-minute job scheduler and the dashboard at **http://localhost:5173**.
Jobs are found while the window is open; Ctrl+C stops it. Before the first run, set
`CURRENT_EMPLOYER_NAMES` in `.env` (created on first run — stop, edit, start again).
Optional: Gmail app password for email alerts/LinkedIn-alert reading, an LLM key, your contact details.

## Optional: always-on cloud mode (GitHub Actions + Neon) — ~15 minutes

1. **Database** — create a free project at [neon.tech](https://neon.tech), copy the connection string.
2. **Gmail app password** — enable 2-Step Verification, then create one at
   <https://myaccount.google.com/apppasswords>. Used for sending alerts and (read-only) reading
   LinkedIn/Naukri job-alert emails. Turn on LinkedIn/Naukri job alerts for your target roles.
3. **Local config**
   ```bash
   cp .env.example .env      # fill SECRET_KEY, DATABASE_URL (Neon), CURRENT_EMPLOYER_*, SMTP_*, GMAIL_*
   cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
   set -a; source ../.env; set +a
   .venv/bin/alembic upgrade head
   .venv/bin/python -m app.cli create-user you@example.com
   .venv/bin/python -m app.cli bootstrap
   .venv/bin/python -m app.cli pipeline --force     # first run: ~2 min, ~10k jobs
   .venv/bin/python -m app.cli top --limit 20
   ```
4. **GitHub Actions = your free server** — push the repo, then add the same values as repository
   secrets (Settings → Secrets → Actions): `SECRET_KEY, DATABASE_URL, CURRENT_EMPLOYER_NAMES,
   CURRENT_EMPLOYER_DOMAINS, SMTP_USER, SMTP_PASSWORD, NOTIFY_EMAIL_TO, GMAIL_IMAP_USER,
   GMAIL_IMAP_APP_PASSWORD` (+ optional `ADZUNA_APP_ID, ADZUNA_APP_KEY, JSEARCH_API_KEY,
   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID`). The `hunt` workflow then runs every 15 minutes.
   - Public repo: unlimited free minutes (secrets stay private; the employer name lives only in secrets).
   - Private repo: 2,000 free min/month → change the cron to `0 * * * *` (hourly).

## Daily use (30–45 min)

```bash
# terminal 1 — API                      # terminal 2 — dashboard
cd backend && set -a && source ../.env && set +a && .venv/bin/uvicorn app.main:app
cd frontend && npm install && npm run dev        # → http://localhost:5173
```

1. **Overview** → 🔥 fresh high matches (also arrive by email every 15 min).
2. Open a job → **Prepare application** → **Review Queue**: edit resume/cover letter → **Approve**.
3. Submit: open the link, or `python -m app.cli autofill <id>` (fills the form, *you* click submit) →
   paste the confirmation reference → **I submitted it**.
4. **Outreach** → Referrals: draft a referral ask to a connection at that company → approve → send/copy.
5. **Tracker**: drag cards as recruiters respond; log interviews to get a prep pack.
6. Weekly: **Analytics** → *Learn from outcomes*; check the skill-gap radar on Overview.

Optional local autofill: `pip install -r backend/requirements-autofill.txt && playwright install chromium`.

## Development

```bash
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests alembic
```
Optional always-on local stack: `docker compose up` (add `--profile scheduler` for Celery worker + beat).
