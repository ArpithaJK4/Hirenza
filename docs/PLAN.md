# Hirenza — AI Job Hunter: Implementation Plan

Goal: maximise **interviews** (not just applications) within 30 days for Python Backend /
DevOps / Platform / DevSecOps / SRE / Cloud roles. India first, then worldwide.

## Guiding principles

1. **Speed beats volume.** Applying within hours of posting matters more than applying everywhere.
2. **Warm beats cold.** Referrals and hiring-manager outreach convert far better than portals.
3. **Compliant sources only.** No scraping of LinkedIn/Naukri/Instahyre/Foundit, no CAPTCHA or
   rate-limit bypass. Those platforms are reached through their own job-alert emails
   (read from your inbox) and manual apply with a prepared packet.
4. **Human in the loop.** Nothing is submitted or sent without explicit approval. Nothing is
   marked "submitted" without a real confirmation.
5. **Never fabricate.** No invented jobs, contacts, confirmations or interview results.
6. **Degrade gracefully.** One failing source or LLM provider never stops the pipeline.
7. **The tool is also the portfolio.** Built and deployed with Terraform, Helm, EKS, a DevSecOps
   CI pipeline and Prometheus/Grafana so it doubles as an interview showcase.

## Confidentiality guardrails (hard blocks, enforced in code)

The candidate is job-hunting while employed. These are not toggles:

1. **No LinkedIn posting or automated LinkedIn actions** of any kind. LinkedIn is read-only
   (alert emails) and messages are drafts the user sends manually.
2. **Never contact current-company employees.** Recruiters/contacts/referral candidates whose
   company matches the current-employer exclusion list are dropped before any draft is made.
3. **Never apply to current-company jobs.** Listings from excluded employers are tagged
   `excluded` at discovery and can never enter matching, alerts or the application queue.

The exclusion list (`CURRENT_EMPLOYER_NAMES`, `CURRENT_EMPLOYER_DOMAINS`) is matched on
normalised company names, aliases and email/web domains. Every block is written to the audit log.

## How a day works

```
every 15 min:  sources ─► discover (dedupe) ─► score ─► [score ≥ alert threshold] ─► Telegram ping
background:    tailored resume + cover letter + autofilled form + outreach draft + referral hint
you (30-45m):  review queue ─► approve ─► submit / send ─► Kanban tracker ─► follow-up reminders
weekly:        outcomes ─► optimisation agent re-weights ranking; skill-gap radar report
```

## The five core agents

| Agent | Implementation |
|---|---|
| 1. Discovery | Greenhouse / Lever / Ashby public job-board APIs for a curated company list; Remote OK API; We Work Remotely RSS; Adzuna API (India + intl); JSearch API (Google-Jobs aggregate incl. LinkedIn/Indeed); LinkedIn & Naukri **alert emails** via IMAP. Incremental sync, cross-source dedupe, closed-job detection. |
| 2. Matching | Layer 1: hard filters + weighted rules (title, skills, experience, location, freshness, salary). Layer 2: embeddings (pgvector). Layer 3: LLM re-rank + explanation on the top slice only. Configurable thresholds and weights. |
| 3. Application | Resume versions, role-tailored ATS resumes (PDF), cover letters, Playwright autofill for Greenhouse/Lever/Ashby that **stops before submit**; manual-apply packets for LinkedIn/Naukri. Duplicate-application block. |
| 4. Outreach | Company hiring pages, public recruiter/hiring-manager info, LinkedIn notes (<300 chars), emails, follow-ups. Copy/send by you. Duplicate-message block. |
| 5. Tracking & optimisation | Kanban CRM, follow-up reminders, per-source/per-role conversion analytics, outcome-driven ranking weights. |

## Smarter additions (all included)

| # | Feature | What it does | Phase |
|---|---|---|---|
| 1 | **Referral finder** | Import your LinkedIn connections export (CSV, from LinkedIn's own data-export) + alumni/ex-colleague lists; cross-match against top-ranked companies; draft referral asks. | 4 |
| 2 | **Speed alerts** | 15-min discovery tick, freshness-first ranking, instant Telegram ping for high matches. | 1 |
| 3 | **Skill-gap radar** | Aggregates skills demanded by matching jobs that are missing from your profile; weekly "learn/add this" report. | 1 (basic), 7 (trends) |
| 4 | **Proof-of-work outreach** | Runs Trivy on a target company's **public** container images / open-source repos and drafts a helpful, non-alarmist note or PR suggestion. Public data only. | 6 |
| 5 | **Hiring-signal radar** | Watches startup funding news RSS (Inc42, YourStory, TechCrunch); flags freshly funded companies for pre-emptive outreach. | 6 |
| 6 | **Interview prep agent** | When a card moves to Interview: likely questions from the JD + company stack, STAR stories from your projects, mock-interview chat. | 7 |
| 7 | **Resume A/B testing** | Rotates resume variants per role family and tracks callback rate per variant. | 4 / 7 |
| 8 | **Ghost-job & scam filter** | Flags stale reposts, fee/deposit requests, WhatsApp-only contact, unrealistic pay, missing company. | 1 |
| 9 | **Portfolio deployment** | Terraform (AWS VPC/EKS/RDS), Helm chart, GitHub Actions with SonarQube/Trivy/Snyk/OWASP DC gates, Prometheus + Grafana. | 10 |

## Phases

| Phase | Days | Deliverable | Status |
|---|---|---|---|
| 1 | 1–3 | Project skeleton, DB + migrations, auth, Docker Compose, discovery engine, rule-based matching, ghost filter, speed alerts (email/Telegram), skill-gap API, CLI, tests, CI | **done** |
| 2 | 4–6 | LLM provider abstraction, resume upload/parsing, embeddings, LLM re-rank; tailored resume + cover letter; review queue API; React dashboard v1 || **done** |
| 3 | 4–6 | Playwright autofill (Greenhouse/Lever/Ashby, stop-before-submit), application queue, duplicate block, confirmation tracking || **done** |
| 4 | 4–6 | Referral finder, resume A/B variants || **done** |
| 5 | 7–9 | Recruiter outreach agent, approval + send log, follow-ups || **done** |
| 6 | 7–9 | Kanban tracker, analytics, reminders; hiring-signal radar; proof-of-work scanner || **done** |
| 7 | 10–12 | Interview prep agent, optimisation agent (outcome-weighted ranking), A/B reporting || **done** |
| 8 | 10–12 | Dashboard completion (10 pages), notification preferences || **done** |
| 9 | 13+ | Orchestration hardening, failure notifications, backups || **done** |
| 10 | 13+ | Security review, Terraform + Helm + EKS, full DevSecOps pipeline, monitoring || partial: security review, CI DevSecOps, Docker done; Terraform/Helm/EKS + Prometheus to do |

## Zero-cost runtime (no server)

| Need | Free option |
|---|---|
| 15-min scheduler | GitHub Actions cron (`.github/workflows/hunt.yml`) |
| Database | Neon Postgres free tier |
| Alerts | Gmail SMTP with App Password (Telegram optional) |
| Dashboard + Playwright autofill | run locally during the daily review session |
| LLM (phase 2) | rules first; LLM only on top-ranked jobs, cached; cheap model for scoring, stronger model for resume/cover letter |

Celery/Redis/Docker Compose remain for an always-on deployment (phase 10: AWS EKS portfolio build).

## Stack

FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL (+pgvector) · Redis · Celery + Beat · Playwright ·
React + TypeScript + Tailwind · Docker Compose · Nginx · GitHub Actions · Terraform · Helm.
