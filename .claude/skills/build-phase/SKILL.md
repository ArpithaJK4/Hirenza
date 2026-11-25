---
name: build-phase
description: Implement the next Hirenza phase from docs/PLAN.md end-to-end (models, migration, services, API, tests, docs). Use when the user says "next phase", "continue building", or names a phase.
---

1. Read the Phases table in `docs/PLAN.md` and pick the first phase not marked done (or the one named).
   Re-read the HARD guardrails in CLAUDE.md — they apply to every phase.
2. Plan the minimal set of files; reuse existing modules (guardrails, notifications.notify, pipeline.run_agent).
3. Models in `app/models/__init__.py` with indexes/unique constraints (e.g. duplicate-application and
   duplicate-message blocks), then autogenerate a migration with the next `--rev-id`.
4. Services under `app/agents/<agent>/`, API routes under `app/api/routes/`, wire into `app/main.py`.
   Anything that submits/sends must require an explicit `approved` state set by a human API call.
5. LLM work: go through `app/llm/` provider abstraction; only for already high-ranked jobs; cache by content hash.
6. Tests (unit + API) → `pytest -q` → `ruff check` → fix until green.
7. Update the phase status in `docs/PLAN.md`; commit with a clear message when the user asks.
