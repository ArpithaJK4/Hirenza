from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.agents.matching.service import WEIGHTS_KEY, get_weights, skill_gaps
from app.api.deps import admin_user, audit, current_profile, current_user
from app.core.db import get_db
from app.core.timeutil import utcnow
from app.models import AgentExecution, CandidateProfile, JobListing, JobMatch, JobSource, SystemConfig, User
from app.schemas import ConfigIn, ExecutionOut, ProfileOut, ProfileUpdate, SourceOut, SourceUpdate

health = APIRouter(tags=["health"])
router = APIRouter(prefix="/api", tags=["system"])


@health.get("/health")
def live():
    return {"status": "ok"}


@health.get("/health/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"database unavailable: {type(e).__name__}") from e
    return {"status": "ready"}


@router.get("/profile", response_model=ProfileOut)
def get_profile(profile: CandidateProfile = Depends(current_profile)):
    return profile


@router.put("/profile", response_model=ProfileOut)
def update_profile(body: ProfileUpdate, request: Request, db: Session = Depends(get_db),
                   profile: CandidateProfile = Depends(current_profile), user: User = Depends(current_user)):
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(profile, k, v)
    audit(db, request, user, "profile.update", "candidate_profile", profile.id, fields=sorted(changes))
    db.commit()
    return profile


@router.get("/sources", response_model=list[SourceOut])
def sources(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return list(db.scalars(select(JobSource).order_by(JobSource.key)))


@router.patch("/sources/{key}", response_model=SourceOut)
def update_source(key: str, body: SourceUpdate, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(admin_user)):
    src = db.scalar(select(JobSource).where(JobSource.key == key))
    if not src:
        raise HTTPException(404, "Unknown source")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(src, k, v)
    audit(db, request, user, "source.update", "job_source", key, **body.model_dump(exclude_unset=True))
    db.commit()
    return src


@router.post("/agents/pipeline/run")
def run_now(request: Request, force: bool = False, db: Session = Depends(get_db),
            user: User = Depends(admin_user)):
    from app.workers.pipeline import run_pipeline
    audit(db, request, user, "agent.run", "pipeline", force=force)
    db.commit()
    return run_pipeline(db, trigger="api", force=force)


@router.get("/agents/executions", response_model=list[ExecutionOut])
def executions(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return list(db.scalars(select(AgentExecution).order_by(AgentExecution.id.desc()).limit(min(limit, 200))))


@router.get("/insights/summary")
def summary(db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    now = utcnow()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    active = (JobListing.is_active.is_(True), JobListing.is_excluded.is_(False),
              JobListing.duplicate_of_id.is_(None))
    count = lambda *w: db.scalar(select(func.count(JobListing.id)).where(*w)) or 0  # noqa: E731
    high = db.scalar(select(func.count(JobMatch.id)).join(JobListing, JobListing.id == JobMatch.job_id)
                     .where(*active, JobMatch.profile_id == profile.id, JobMatch.is_suspicious.is_(False),
                            JobMatch.score >= profile.alert_threshold)) or 0
    return {
        "jobs_discovered_today": count(JobListing.discovered_at >= day, JobListing.duplicate_of_id.is_(None)),
        "new_last_24h": count(*active, JobListing.posted_at >= now - timedelta(hours=24)),
        "active_jobs": count(*active),
        "highly_relevant": high,
        **_crm_counts(db, profile.id),
    }


def _crm_counts(db: Session, profile_id: int) -> dict:
    from app.models import Application, Interview, Offer, OutreachMessage, Recruiter
    apps = lambda *w: db.scalar(select(func.count(Application.id)).where(  # noqa: E731
        Application.profile_id == profile_id, *w)) or 0
    return {
        "pending_approvals": apps(Application.status == "prepared"),
        "applications_submitted": apps(Application.status == "submitted"),
        "recruiters_contacted": db.scalar(select(func.count(func.distinct(OutreachMessage.recruiter_id)))
                                          .join(Recruiter).where(Recruiter.profile_id == profile_id,
                                                                 OutreachMessage.status.in_(["sent", "replied"]))) or 0,
        "interview_calls": db.scalar(select(func.count(Interview.id)).join(Application)
                                     .where(Application.profile_id == profile_id)) or 0,
        "offers": db.scalar(select(func.count(Offer.id)).join(Application)
                            .where(Application.profile_id == profile_id)) or 0,
    }


@router.get("/insights/skill-gaps")
def gaps(days: int = 14, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    return skill_gaps(db, profile.id, days=max(1, min(days, 90)))


@router.get("/config/matching-weights")
def get_matching_weights(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return get_weights(db)


@router.put("/config/matching-weights")
def set_matching_weights(body: ConfigIn, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(admin_user)):
    allowed = set(get_weights(db))
    bad = set(body.value) - allowed
    if bad or not all(isinstance(v, int | float) and 0 <= v <= 1 for v in body.value.values()):
        raise HTTPException(422, f"weights must be numbers 0-1 for keys {sorted(allowed)}")
    cfg = db.scalar(select(SystemConfig).where(SystemConfig.key == WEIGHTS_KEY)) or SystemConfig(key=WEIGHTS_KEY)
    cfg.value = body.value
    db.add(cfg)
    audit(db, request, user, "config.update", "system_config", WEIGHTS_KEY, value=body.value)
    db.commit()
    return get_weights(db)
