from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.outreach import service as svc
from app.api.deps import audit, current_profile, current_user
from app.core.db import get_db
from app.models import CandidateProfile, CompanySignal, JobListing, OutreachMessage, Recruiter, User

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


class PersonIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    title: str = Field("", max_length=200)
    email: EmailStr | None = None
    linkedin_url: str | None = Field(None, max_length=500, pattern=r"^https://(www\.)?linkedin\.com/.*")
    relationship_type: str = Field("recruiter", pattern="^(recruiter|hiring_manager|connection)$")
    notes: str = Field("", max_length=2000)


class PersonOut(BaseModel):
    id: int
    name: str
    company_name: str
    title: str
    email: str | None
    linkedin_url: str | None
    relationship_type: str
    source: str
    is_excluded: bool
    model_config = {"from_attributes": True}


class MsgOut(BaseModel):
    id: int
    recruiter_id: int
    job_id: int | None
    channel: str
    sequence: int
    subject: str
    body: str
    status: str
    generated_by: str
    sent_at: datetime | None
    replied_at: datetime | None
    created_at: datetime
    recruiter_name: str = ""
    company: str = ""
    model_config = {"from_attributes": True}


def _msg_out(m: OutreachMessage) -> MsgOut:
    return MsgOut.model_validate(m).model_copy(update={"recruiter_name": m.recruiter.name,
                                                       "company": m.recruiter.company_name})


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except svc.OutreachBlocked as e:
        raise HTTPException(409, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@router.get("/people", response_model=list[PersonOut])
def people(relationship_type: str | None = None, q: str | None = None, db: Session = Depends(get_db),
           profile: CandidateProfile = Depends(current_profile)):
    stmt = select(Recruiter).where(Recruiter.profile_id == profile.id)
    if relationship_type:
        stmt = stmt.where(Recruiter.relationship_type == relationship_type)
    if q:
        stmt = stmt.where(Recruiter.company_name.ilike(f"%{q}%") | Recruiter.name.ilike(f"%{q}%"))
    return list(db.scalars(stmt.order_by(Recruiter.company_name).limit(500)))


@router.post("/people", response_model=PersonOut, status_code=201)
def add_person(body: PersonIn, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    r = svc.upsert_person(db, profile.id, **body.model_dump())
    db.commit()
    return r


@router.post("/import-linkedin-connections")
async def import_connections(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                             profile: CandidateProfile = Depends(current_profile), user: User = Depends(current_user)):
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "File too large")
    out = _guard(svc.import_linkedin_connections, db, profile.id, data)
    audit(db, request, user, "outreach.import_connections", details_count=out["imported"])
    db.commit()
    return out


@router.get("/referrals")
def referrals(db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    return svc.referral_suggestions(db, profile.id)


class DraftIn(BaseModel):
    recruiter_id: int
    job_id: int | None = None
    channel: str = Field(pattern="^(linkedin_note|email|referral_request|follow_up)$")
    context: str = Field("", max_length=1000)


@router.post("/messages", response_model=MsgOut, status_code=201)
def draft(body: DraftIn, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    r = db.get(Recruiter, body.recruiter_id)
    if not r or r.profile_id != profile.id:
        raise HTTPException(404, "Person not found")
    job = db.get(JobListing, body.job_id) if body.job_id else None
    return _msg_out(_guard(svc.create_draft, db, r, body.channel, job, body.context))


@router.get("/messages", response_model=list[MsgOut])
def messages(status: str | None = None, db: Session = Depends(get_db),
             profile: CandidateProfile = Depends(current_profile)):
    q = select(OutreachMessage).join(Recruiter).where(Recruiter.profile_id == profile.id)
    if status:
        q = q.where(OutreachMessage.status == status)
    return [_msg_out(m) for m in db.scalars(q.order_by(OutreachMessage.id.desc()).limit(300))]


def _msg(db, profile, mid) -> OutreachMessage:
    m = db.get(OutreachMessage, mid)
    if not m or m.recruiter.profile_id != profile.id:
        raise HTTPException(404, "Message not found")
    return m


class MsgEdit(BaseModel):
    subject: str = Field("", max_length=300)
    body: str = Field(min_length=5, max_length=5000)


@router.put("/messages/{mid}", response_model=MsgOut)
def edit(mid: int, body: MsgEdit, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    m = _msg(db, profile, mid)
    if m.status not in ("draft", "approved"):
        raise HTTPException(409, "Already sent")
    if m.channel == "linkedin_note" and len(body.body) > svc.LINKEDIN_NOTE_LIMIT:
        raise HTTPException(422, f"LinkedIn notes must be ≤ {svc.LINKEDIN_NOTE_LIMIT} characters")
    m.subject, m.body, m.status, m.generated_by = body.subject, body.body, "draft", "edited"
    db.commit()
    return _msg_out(m)


@router.post("/messages/{mid}/{action}", response_model=MsgOut)
def act(mid: int, action: str, request: Request, db: Session = Depends(get_db),
        profile: CandidateProfile = Depends(current_profile), user: User = Depends(current_user)):
    m = _msg(db, profile, mid)
    fns = {"approve": svc.approve_message, "send": svc.send_message, "mark-sent": svc.mark_sent}
    if action == "reject":
        m.status = "rejected"
        db.commit()
    elif action == "mark-replied":
        if m.status != "sent":
            raise HTTPException(409, "Only sent messages can get replies")
        from app.core.timeutil import utcnow
        m.status, m.replied_at = "replied", utcnow()
        db.commit()
    elif action in fns:
        _guard(fns[action], db, m)
    else:
        raise HTTPException(404, "Unknown action")
    audit(db, request, user, f"outreach.{action}", "outreach_message", mid)
    db.commit()
    return _msg_out(m)


@router.get("/signals")
def signals(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.scalars(select(CompanySignal).order_by(CompanySignal.published_at.desc().nulls_last()).limit(100))
    return [{"company": s.company_name, "title": s.title, "url": s.url, "source": s.source,
             "published_at": s.published_at} for s in rows]


class ScanIn(BaseModel):
    image: str = Field(min_length=3, max_length=200)


@router.post("/proof-of-work")
def proof_of_work(body: ScanIn, _: User = Depends(current_user)):
    return _guard(svc.proof_of_work_scan, body.image)
