#!/usr/bin/env bash
# Hirenza laptop mode: API + 15-min scheduler + dashboard. No server, no cloud accounts needed.
# Usage: ./scripts/start-local.sh          (Ctrl+C stops everything)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "Creating .env (local SQLite database)…"
  cp .env.example .env
  KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=$KEY|" .env
  sed -i.bak "s|^DATABASE_URL=.*|DATABASE_URL=sqlite:///$ROOT/backend/data/hirenza.db|" .env
  rm -f .env.bak
  echo ">> Edit .env to add CURRENT_EMPLOYER_NAMES (important) and optional Gmail/LLM settings."
fi
set -a; source .env; set +a

cd backend
if [ ! -x .venv/bin/python ]; then
  echo "Setting up Python environment (first run only)…"
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli bootstrap >/dev/null
if [ "$(.venv/bin/python -c 'from app.core.db import session_scope
from app.models import User
from sqlalchemy import select
with session_scope() as db: print(1 if db.scalar(select(User.id)) else 0)')" = "0" ]; then
  echo "Create your login (used for the dashboard):"
  read -rp "Email: " EMAIL
  .venv/bin/python -m app.cli create-user "$EMAIL"
fi

cd "$ROOT/frontend"
[ -d node_modules ] || { echo "Installing dashboard (first run only)…"; npm install --silent; }

cd "$ROOT/backend"
pids=()
cleanup() { echo; echo "Stopping…"; kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning & pids+=($!)
.venv/bin/python -m app.cli scheduler --every "${HUNT_EVERY_MINUTES:-15}" & pids+=($!)
(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 --port 5173 >/dev/null) & pids+=($!)
sleep 3
echo ""
echo "  Dashboard:  http://localhost:5173"
echo "  API docs:   http://localhost:8000/docs"
echo "  The scheduler finds and scores jobs every ${HUNT_EVERY_MINUTES:-15} min while this window is open."
echo "  First run fetches ~10,000 jobs (about 2 minutes)."
echo ""
wait
