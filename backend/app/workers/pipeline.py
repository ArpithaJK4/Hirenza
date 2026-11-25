"""Orchestrates the agents. Same entry point for GitHub Actions (CLI), Celery Beat and the API."""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.discovery.service import run_discovery
from app.agents.matching.service import run_matching
from app.core.timeutil import utcnow
from app.models import AgentExecution
from app.notifications.alerts import notify_failing_sources, send_job_alerts

log = logging.getLogger(__name__)
STALE_AFTER = timedelta(minutes=20)


def _already_running(db: Session, agent: str) -> bool:
    return db.scalar(select(AgentExecution.id).where(
        AgentExecution.agent == agent, AgentExecution.status == "running",
        AgentExecution.started_at >= utcnow() - STALE_AFTER)) is not None


def run_agent(db: Session, agent: str, fn, trigger: str = "schedule") -> AgentExecution:
    """Run one agent step with execution history and an idempotency guard."""
    if _already_running(db, agent):
        ex = AgentExecution(agent=agent, trigger=trigger, status="skipped", finished_at=utcnow(),
                            stats={"reason": "previous run still in progress"})
        db.add(ex)
        db.commit()
        return ex
    ex = AgentExecution(agent=agent, trigger=trigger, status="running", started_at=utcnow())
    db.add(ex)
    db.commit()
    try:
        stats = fn(db)
        ex.status = "partial" if any(s.get("errors") for s in (stats.get("sources") or {}).values()) \
            else "success"
        ex.stats = stats
    except Exception as e:
        db.rollback()
        ex.status, ex.error = "failed", repr(e)[:2000]
        log.exception("agent failed", extra={"ctx": {"agent": agent}})
    ex.finished_at = utcnow()
    db.commit()
    return ex


def run_pipeline(db: Session, trigger: str = "schedule", force: bool = False,
                 only: list[str] | None = None) -> dict:
    d = run_agent(db, "discovery", lambda s: run_discovery(s, only=only, force=force), trigger)
    m = run_agent(db, "matching", run_matching, trigger)
    a = run_agent(db, "alerts", send_job_alerts, trigger)
    if d.status in ("success", "partial"):
        notify_failing_sources(db, d.stats.get("failing_sources", []))
    from app.agents.application.auto_apply import run_auto_apply
    from app.agents.outreach.service import refresh_signals
    from app.agents.tracking.service import prune, send_reminders
    from app.core.config import get_settings
    if get_settings().auto_apply_enabled and trigger in ("laptop", "cli", "api"):
        aa = run_agent(db, "auto_apply", run_auto_apply, trigger)
    r = run_agent(db, "reminders", send_reminders, trigger)
    extras = {"reminders": r.stats}
    if get_settings().auto_apply_enabled and trigger in ("laptop", "cli", "api"):
        extras["auto_apply"] = aa.stats
    if utcnow().minute < 15:  # hourly housekeeping
        extras["signals"] = run_agent(db, "signals", refresh_signals, trigger).stats
        extras["prune"] = run_agent(db, "prune", prune, trigger).stats
    return {**extras, "discovery": {"status": d.status, **(d.stats or {})},
            "matching": {"status": m.status, **(m.stats or {})},
            "alerts": {"status": a.status, **(a.stats or {})}}
