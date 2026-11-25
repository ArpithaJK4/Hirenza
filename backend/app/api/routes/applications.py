from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.application import service as svc
from app.agents.application.resume import ResumeError, parse_resume, render_pdf
from app.api.deps import audit, current_profile, current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.models import Application, ApplicationDocument, CandidateProfile, JobMatch, Resume, User

router = APIRouter(prefix="/api", tags=["resumes & applications"])


class ResumeOut(BaseModel):
    id: int
    name: str
    file_name: str
    skills: list[str]
    is_default: bool
    created_at: datetime
    sections: dict = {}
    model_config = {"from_attributes": True}


def _resume(db, profile, rid) -> Resume:
    r = db.get(Resume, rid)
    if not r or r.profile_id != profile.id:
        raise HTTPException(404, "Resume not found")
    return r


@router.post("/resumes", response_model=ResumeOut, status_code=201)
async def upload_resume(request: Request, file: UploadFile = File(...), name: str = "Main",
                        db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile),
                        user: User = Depends(current_user)):
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File larger than {get_settings().max_upload_mb} MB")
    fname = (file.filename or "resume").replace("/", "_").replace("\\", "_")[-200:]
    try:
        parsed = parse_resume(data, fname)
    except ResumeError as e:
        raise HTTPException(422, str(e)) from e
    first = db.scalar(select(Resume.id).where(Resume.profile_id == profile.id)) is None
    r = Resume(profile_id=profile.id, name=name[:120], file_name=fname, content_type=file.content_type or "",
               file_data=data, text=parsed["text"], sections=parsed["sections"], skills=parsed["skills"],
               is_default=first)
    db.add(r)
    profile.resume_text = profile.resume_text or parsed["text"]
    audit(db, request, user, "resume.upload", "resume", None, file=fname)
    db.commit()
    return r


@router.get("/resumes", response_model=list[ResumeOut])
def list_resumes(db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    return list(db.scalars(select(Resume).where(Resume.profile_id == profile.id).order_by(Resume.id.desc())))


@router.post("/resumes/{rid}/default", response_model=ResumeOut)
def set_default(rid: int, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    r = _resume(db, profile, rid)
    for other in db.scalars(select(Resume).where(Resume.profile_id == profile.id)):
        other.is_default = other.id == r.id
    db.commit()
    return r


@router.delete("/resumes/{rid}", status_code=204)
def delete_resume(rid: int, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    db.delete(_resume(db, profile, rid))
    db.commit()


class DocOut(BaseModel):
    kind: str
    content: str
    generated_by: str
    model_config = {"from_attributes": True}


class AppOut(BaseModel):
    id: int
    job_id: int
    status: str
    stage: str
    resume_variant: str
    apply_method: str
    match_score: float | None
    approved_at: datetime | None
    submitted_at: datetime | None
    confirmation_ref: str | None
    follow_up_at: datetime | None
    notes: str
    created_at: datetime
    job_title: str = ""
    company: str = ""
    apply_url: str | None = None
    source: str = ""
    model_config = {"from_attributes": True}


class AppDetail(AppOut):
    documents: list[DocOut]
    form_fields: list[dict]
    description: str = ""
    explanation: str = ""
    missing_skills: list[str] = []
    autofill_preview: dict = {}


def _out(a: Application, detail: bool = False, db: Session | None = None):
    base = {c: getattr(a, c) for c in AppOut.model_fields if hasattr(a, c)}
    base.update(job_title=a.job.title, company=a.job.company_name, apply_url=a.job.apply_url or a.job.url,
                source=a.job.source.key)
    if not detail:
        return AppOut(**base)
    m = db.scalar(select(JobMatch).where(JobMatch.job_id == a.job_id, JobMatch.profile_id == a.profile_id))
    preview = {k: (v if k in ("first_name", "last_name", "location") else ("✓ set" if v else "— not set"))
               for k, v in svc._autofill_values().items()}
    return AppDetail(**base, documents=[DocOut.model_validate(d) for d in a.documents], form_fields=a.form_fields,
                     description=a.job.description, explanation=m.explanation if m else "",
                     missing_skills=m.missing_skills if m else [], autofill_preview=preview)


def _app(db, profile, aid) -> Application:
    a = db.get(Application, aid)
    if not a or a.profile_id != profile.id:
        raise HTTPException(404, "Application not found")
    return a


def _blocked(fn, *args):
    try:
        return fn(*args)
    except svc.ApplicationBlocked as e:
        raise HTTPException(409, str(e)) from e


@router.post("/jobs/{job_id}/prepare", response_model=AppDetail, status_code=201)
def prepare(job_id: int, request: Request, db: Session = Depends(get_db),
            profile: CandidateProfile = Depends(current_profile), user: User = Depends(current_user)):
    a = _blocked(svc.prepare_application, db, profile, job_id)
    audit(db, request, user, "application.prepare", "application", a.id, job_id=job_id)
    db.commit()
    return _out(a, True, db)


@router.get("/applications", response_model=list[AppOut])
def list_apps(status: str | None = None, stage: str | None = None, db: Session = Depends(get_db),
              profile: CandidateProfile = Depends(current_profile)):
    q = select(Application).where(Application.profile_id == profile.id)
    if status:
        q = q.where(Application.status == status)
    if stage:
        q = q.where(Application.stage == stage)
    return [_out(a) for a in db.scalars(q.order_by(Application.match_score.desc().nulls_last(), Application.id))]


@router.get("/applications/{aid}", response_model=AppDetail)
def get_app(aid: int, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    return _out(_app(db, profile, aid), True, db)


class DocEdit(BaseModel):
    kind: str = Field(pattern="^(resume|cover_letter)$")
    content: str = Field(min_length=20, max_length=30000)


@router.put("/applications/{aid}/documents", response_model=AppDetail)
def edit_doc(aid: int, body: DocEdit, db: Session = Depends(get_db),
             profile: CandidateProfile = Depends(current_profile)):
    a = _app(db, profile, aid)
    if a.status == "submitted":
        raise HTTPException(409, "Already submitted")
    doc = next((d for d in a.documents if d.kind == body.kind), None) or ApplicationDocument(
        application_id=a.id, kind=body.kind, content="")
    doc.content, doc.generated_by = body.content, "edited"
    db.add(doc)
    db.commit()
    return _out(a, True, db)


@router.get("/applications/{aid}/resume.pdf")
def resume_pdf(aid: int, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    a = _app(db, profile, aid)
    doc = next((d for d in a.documents if d.kind == "resume"), None)
    if not doc:
        raise HTTPException(404, "No resume document")
    return Response(render_pdf(doc.content), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="resume-{a.id}.pdf"'})


@router.post("/applications/{aid}/approve", response_model=AppOut)
def approve(aid: int, request: Request, db: Session = Depends(get_db),
            profile: CandidateProfile = Depends(current_profile), user: User = Depends(current_user)):
    a = _blocked(svc.approve, db, _app(db, profile, aid))
    audit(db, request, user, "application.approve", "application", aid)
    db.commit()
    return _out(a)


class RejectIn(BaseModel):
    reason: str = Field("", max_length=500)


@router.post("/applications/{aid}/reject", response_model=AppOut)
def reject(aid: int, body: RejectIn, request: Request, db: Session = Depends(get_db),
           profile: CandidateProfile = Depends(current_profile), user: User = Depends(current_user)):
    a = _blocked(svc.reject, db, _app(db, profile, aid), body.reason)
    audit(db, request, user, "application.reject", "application", aid)
    db.commit()
    return _out(a)


class SubmittedIn(BaseModel):
    confirmation_ref: str = Field(min_length=3, max_length=255)
    source: str = Field("user_attested", pattern="^(email|portal|user_attested)$")


@router.post("/applications/{aid}/submitted", response_model=AppOut)
def submitted(aid: int, body: SubmittedIn, request: Request, db: Session = Depends(get_db),
              profile: CandidateProfile = Depends(current_profile), user: User = Depends(current_user)):
    a = _blocked(svc.mark_submitted, db, _app(db, profile, aid), body.confirmation_ref, body.source)
    audit(db, request, user, "application.submitted", "application", aid, ref=body.confirmation_ref)
    db.commit()
    return _out(a)
