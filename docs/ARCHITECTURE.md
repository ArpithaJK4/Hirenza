# Hirenza — Architecture

## 1. System context

```mermaid
flowchart LR
    subgraph Sources["Job & signal sources (compliant only)"]
        ATS[Greenhouse / Lever / Ashby<br/>public board APIs]
        AGG[Adzuna API · JSearch API]
        REM[Remote OK API · WWR RSS]
        MAIL[LinkedIn & Naukri<br/>alert emails via IMAP]
        NEWS[Funding news RSS]
        CSV[LinkedIn connections<br/>CSV export]
    end

    subgraph Hirenza
        API[FastAPI]
        W[Celery workers]
        B[Celery Beat]
        DB[(PostgreSQL + pgvector)]
        R[(Redis)]
        PW[Playwright]
        FE[React dashboard]
    end

    LLM[LLM providers<br/>Claude / OpenAI / Ollama]
    TG[Telegram]
    EM[Email SMTP]
    YOU((You))

    Sources --> W
    B --> R --> W
    W <--> DB
    API <--> DB
    W --> LLM
    W --> PW
    W --> TG & EM
    FE --> API
    YOU --> FE
    TG --> YOU
```

## 2. Pipeline and agents

```mermaid
flowchart TD
    T[Beat tick · every 15 min] --> D

    subgraph A1[Agent 1 · Discovery]
        D[Due sources only<br/>per-source rate budget] --> N[Normalise<br/>title/location/salary/exp/skills]
        N --> X{Current-employer<br/>exclusion}
        X -- excluded --> XL[tag excluded + audit]
        X -- ok --> DD[Dedupe<br/>source+id · cross-source fingerprint]
        DD --> CL[Closed-job detection]
    end

    subgraph A2[Agent 2 · Matching]
        CL --> G[Ghost / scam filter]
        G --> S1[L1 rules: title · skills · exp · location · freshness · salary]
        S1 --> S2[L2 embeddings]
        S2 --> S3[L3 LLM re-rank + why, top slice only]
    end

    S3 --> AL{score ≥ alert threshold<br/>and fresh?}
    AL -- yes --> TG[Telegram speed alert]

    subgraph A3[Agent 3 · Application]
        S3 --> RS[Tailored resume variant A/B]
        RS --> CV[Cover letter]
        CV --> FF[Playwright autofill<br/>STOPS before submit]
    end

    subgraph A4[Agent 4 · Outreach]
        S3 --> RF[Referral finder<br/>connections × top companies]
        S3 --> RC[Recruiter / hiring-manager drafts]
        HS[Hiring-signal radar] --> RC
        PoW[Proof-of-work Trivy scan<br/>public images only] --> RC
        RF & RC --> X2{Current-employer<br/>block}
    end

    FF --> Q[Human review queue]
    X2 --> Q
    Q -- approve --> SUB[You submit / send]
    Q -- reject --> REJ[Rejected]

    subgraph A5[Agent 5 · Tracking & optimisation]
        SUB --> K[Kanban CRM + follow-ups]
        K --> IP[Interview prep agent]
        K --> AN[Analytics: per source / role / resume variant]
        AN --> OPT[Re-weight ranking]
        AN --> GAP[Skill-gap radar]
    end

    OPT --> S1
```

Agents are independent Celery tasks. They communicate only through database records
(`job_listings → job_matches → application_documents → applications …`), so any agent can
fail, retry or be re-run without breaking the others.

## 3. Code layout

```
backend/
  app/
    main.py                 FastAPI app, middleware, routers
    cli.py                  hirenza CLI (discover, score, top, skill-gaps …)
    core/                   config, db, security (JWT, argon2), logging, rate limits
    models/                 SQLAlchemy models
    schemas/                Pydantic request/response models
    api/routes/             auth, profile, jobs, sources, agents, insights, config, health
    guardrails/             current-employer exclusion (used by every agent)
    agents/
      discovery/sources/    one adapter per source (BaseSource interface)
      discovery/service.py  upsert, dedupe, closure detection
      matching/             skills vocab, scorer, ghost filter, service
      application/          resume tailoring, cover letters, playwright fillers   (phase 2-3)
      outreach/             recruiter, referral, signals, proof-of-work           (phase 4-6)
      tracking/             CRM, analytics, optimiser, interview prep             (phase 6-7)
    llm/                    provider abstraction + fallbacks                       (phase 2)
    notifications/          telegram, email, dispatcher (idempotent)
    workers/                celery app, beat schedule, tasks, locks
  alembic/                  migrations
  data/                     companies.yaml, profile.yaml (no personal contact data)
  tests/
frontend/                   React + TS + Tailwind                                  (phase 2+)
deploy/                     nginx, terraform, helm                                 (phase 10)
docker-compose.yml
.github/workflows/ci.yml
```

## 4. Data model (core)

```mermaid
erDiagram
    USER ||--|| CANDIDATE_PROFILE : owns
    CANDIDATE_PROFILE ||--o{ RESUME : has
    JOB_SOURCE ||--o{ JOB_LISTING : produced
    COMPANY ||--o{ JOB_LISTING : posts
    JOB_LISTING ||--o{ JOB_MATCH : scored_as
    CANDIDATE_PROFILE ||--o{ JOB_MATCH : for
    JOB_MATCH ||--o{ APPLICATION_DOCUMENT : generates
    JOB_LISTING ||--o| APPLICATION : applied_via
    APPLICATION ||--o{ INTERVIEW : leads_to
    APPLICATION ||--o| OFFER : results_in
    COMPANY ||--o{ RECRUITER : employs
    RECRUITER ||--o{ OUTREACH_MESSAGE : receives
    USER ||--o{ NOTIFICATION : gets
    USER ||--o{ AUDIT_LOG : acts
```

Key constraints: `job_listings(source_id, external_id)` unique, `fingerprint` indexed for
cross-source dedupe, `job_matches(job_id, profile_id)` unique, `applications(profile_id, job_id)`
unique (duplicate-application block), `notifications(channel, dedupe_key)` unique (no repeat alerts),
`outreach_messages(recruiter_id, kind, sequence)` unique (no duplicate messages).

## 5. Reliability and safety

| Concern | Mechanism |
|---|---|
| Overlapping ticks | Redis lock per pipeline run; idempotent upserts |
| Source failure | Per-source try/except, failure counters, auto-disable dead boards, alert after 3 failures |
| Rate limits | Per-source minimum interval + request budget (e.g. Adzuna 2h, JSearch 12h) |
| LLM failure | Provider fallback chain → rule-based score still works |
| Approval | Submit/send endpoints require an `approved` state set by a human action |
| Confidentiality | `guardrails/` exclusion checked at discovery, outreach, referral and application |
| Secrets | `.env` only, `SecretStr`, never logged |
| Auth | JWT, argon2 hashing, login rate limit, audit log |
| Observability | JSON logs, `agent_executions` history, `/health` + `/health/ready`, Prometheus metrics (phase 10) |

## 6. Deployment

```
Zero-cost (now):     GitHub Actions cron → CLI pipeline → Neon Postgres → Gmail SMTP alerts
                     dashboard + Playwright run on the laptop during the daily review
Local / single VM:   docker compose → nginx · api · worker · beat · postgres · redis · frontend
AWS (portfolio):     Terraform → VPC · EKS · RDS Postgres · ElastiCache · S3 (resumes, backups)
                     Helm chart → api / worker / beat / frontend · Ingress (nginx) · cert-manager
CI/CD:               GitHub Actions → ruff · pytest · SonarQube · Snyk · OWASP DC · Trivy (fs+image)
                     → build & push image → helm upgrade (staging → manual approve → prod)
Monitoring:          Prometheus + Grafana dashboards (jobs/hour, source health, task failures)
```
