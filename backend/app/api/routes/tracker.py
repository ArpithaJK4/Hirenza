from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.agents.tracking import service as svc
from app.api.deps import admin_user, current_profile, current_user
from app.core.db import get_db
from app.models import Application, AuditLog, CandidateProfile, Interview, Notification, Offer, Resume, User

router = APIRouter(prefix="/api", tags=["tracker & analytics"])


def _app(db, profile, aid) -> Application:
    a = db.get(Application, aid)
    if not a or a.profile_id != profile.id:
        raise HTTPException(404, "Application not found")
    return a


class StageIn(BaseModel):
    stage: str
    notes: str | None = Field(None, max_length=5000)
    follow_up_at: datetime | None = None


@router.patch("/applications/{aid}/stage")
def set_stage(aid: int, body: StageIn, db: Session = Depends(get_db),
              profile: CandidateProfile = Depends(current_profile)):
    a = _app(db, profile, aid)
    try:
        svc.set_stage(db, a, body.stage)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if body.notes is not None:
        a.notes = body.notes
    if body.follow_up_at:
        a.follow_up_at = body.follow_up_at
    db.commit()
    return {"id": a.id, "stage": a.stage}


class InterviewIn(BaseModel):
    kind: str = Field(pattern="^(screening|technical|hr|managerial)$")
    scheduled_at: datetime | None = None
    notes: str = Field("", max_length=5000)


class InterviewOut(BaseModel):
    id: int
    application_id: int
    kind: str
    scheduled_at: datetime | None
    status: str
    outcome: str
    notes: str
    prep_pack: str
    model_config = {"from_attributes": True}


@router.post("/applications/{aid}/interviews", response_model=InterviewOut, status_code=201)
def add_interview(aid: int, body: InterviewIn, db: Session = Depends(get_db),
                  profile: CandidateProfile = Depends(current_profile)):
    a = _app(db, profile, aid)
    if a.status != "submitted":
        raise HTTPException(409, "Interviews can only be logged for submitted applications")
    i = Interview(application_id=a.id, **body.model_dump())
    db.add(i)
    if a.stage in ("applied", "prepared"):
        a.stage = "screening" if body.kind in ("screening", "hr") else "technical"
    a.follow_up_at = None
    db.flush()
    resume = db.get(Resume, a.resume_id) if a.resume_id else None
    i.prep_pack = svc.interview_prep(db, i, a, resume.text if resume else profile.resume_text)
    db.commit()
    return i


@router.get("/interviews", response_model=list[InterviewOut])
def interviews(db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    return list(db.scalars(select(Interview).join(Application).where(Application.profile_id == profile.id)
                           .order_by(Interview.scheduled_at.desc().nulls_last())))


class InterviewUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(scheduled|done|cancelled)$")
    outcome: str | None = Field(None, pattern="^(pending|passed|failed)$")
    notes: str | None = Field(None, max_length=5000)


@router.patch("/interviews/{iid}", response_model=InterviewOut)
def update_interview(iid: int, body: InterviewUpdate, db: Session = Depends(get_db),
                     profile: CandidateProfile = Depends(current_profile)):
    i = db.get(Interview, iid)
    if not i or _app(db, profile, i.application_id) is None:
        raise HTTPException(404, "Interview not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    db.commit()
    return i


class OfferIn(BaseModel):
    ctc: float | None = Field(None, ge=0)
    currency: str = Field("INR", max_length=8)
    details: str = Field("", max_length=5000)
    status: str = Field("received", pattern="^(received|negotiating|accepted|declined)$")


@router.put("/applications/{aid}/offer")
def offer(aid: int, body: OfferIn, db: Session = Depends(get_db),
          profile: CandidateProfile = Depends(current_profile)):
    a = _app(db, profile, aid)
    if a.status != "submitted":
        raise HTTPException(409, "Offers can only be logged for submitted applications")
    o = db.scalar(select(Offer).where(Offer.application_id == a.id)) or Offer(application_id=a.id)
    for k, v in body.model_dump().items():
        setattr(o, k, v)
    db.add(o)
    a.stage = "hired" if body.status == "accepted" else "offer"
    db.commit()
    return {"application_id": a.id, "status": o.status, "stage": a.stage}


@router.get("/analytics")
def analytics(days: int = 30, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    return svc.analytics(db, profile.id, max(1, min(days, 365)))


@router.post("/analytics/optimise")
def optimise(db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile),
             _: User = Depends(admin_user)):
    return svc.optimise(db, profile.id)


@router.get("/llm/usage")
def llm_usage(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return llm.usage_summary(db)


@router.get("/logs/audit")
def audit_logs(limit: int = 100, db: Session = Depends(get_db), _: User = Depends(admin_user)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)))
    return [{"id": r.id, "action": r.action, "entity": r.entity, "entity_id": r.entity_id, "details": r.details,
             "created_at": r.created_at} for r in rows]


@router.get("/notifications")
def notifications(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(min(limit, 200)))
    return [{"id": n.id, "channel": n.channel, "kind": n.kind, "title": n.title, "status": n.status,
             "error": n.error, "created_at": n.created_at} for n in rows]


@router.get("/auto-apply")
def auto_apply_status(db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    from app.agents.application import auto_apply as aa
    from app.core.config import get_settings
    s = get_settings()
    missing = [k for k in ("candidate_full_name", "candidate_email", "candidate_phone", "candidate_notice_period",
                           "candidate_expected_ctc", "candidate_current_ctc", "candidate_willing_to_relocate")
               if not getattr(s, k)]
    return {"enabled": s.auto_apply_enabled, "dry_run": s.auto_apply_dry_run, "paused": aa.is_paused(db),
            "min_score": s.auto_apply_min_score, "daily_cap": s.auto_apply_daily_cap,
            "used_today": aa.used_today(db, profile.id), "countries": s.auto_apply_countries,
            "missing_answers": missing}


class PauseIn(BaseModel):
    paused: bool


@router.put("/auto-apply/pause")
def auto_apply_pause(body: PauseIn, db: Session = Depends(get_db), _: User = Depends(admin_user)):
    from app.agents.application import auto_apply as aa
    aa.set_paused(db, body.paused)
    return {"paused": body.paused}


@router.post("/auto-apply/test-run")
def auto_apply_test(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    """Always a dry run: fills forms and screenshots, never submits."""
    from app.agents.application.auto_apply import run_auto_apply
    return run_auto_apply(db, force_dry_run=True)
