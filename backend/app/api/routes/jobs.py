from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.api.deps import audit, current_profile, current_user
from app.core.db import get_db
from app.core.timeutil import utcnow
from app.models import CandidateProfile, JobListing, JobMatch, JobSource, User
from app.schemas import JobDetailOut, JobOut, JobPage, MatchOut, MatchStatusIn

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _out(job: JobListing, match: JobMatch | None, detail: bool = False):
    cls = JobDetailOut if detail else JobOut
    data = {c: getattr(job, c) for c in cls.model_fields if c not in ("source", "match")}
    return cls(**data, source=job.source.key, match=MatchOut.model_validate(match) if match else None)


@router.get("", response_model=JobPage)
def list_jobs(
    db: Session = Depends(get_db),
    profile: CandidateProfile = Depends(current_profile),
    q: str | None = Query(None, max_length=100, description="title/company search"),
    country: str | None = None,
    city: str | None = None,
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"] | None = None,
    source: str | None = None,
    min_score: float = Query(0, ge=0, le=100),
    max_experience: float | None = Query(None, ge=0, le=40),
    min_salary_lpa: float | None = Query(None, ge=0),
    posted_within_hours: int | None = Query(None, ge=1, le=24 * 365),
    freshness: Literal["24h", "7d", "older", "unknown"] | None = None,
    status: Literal["new", "shortlisted", "dismissed"] | None = None,
    include_suspicious: bool = False,
    sort: Literal["score", "posted", "discovered"] = "score",
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
):
    stmt = (select(JobListing, JobMatch)
            .join(JobSource, JobSource.id == JobListing.source_id)
            .outerjoin(JobMatch, and_(JobMatch.job_id == JobListing.id, JobMatch.profile_id == profile.id))
            .options(contains_eager(JobListing.source))
            .where(JobListing.is_active.is_(True), JobListing.is_excluded.is_(False),
                   JobListing.duplicate_of_id.is_(None)))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(JobListing.title).like(like), func.lower(JobListing.company_name).like(like)))
    if country:
        stmt = stmt.where(JobListing.country == country)
    if city:
        stmt = stmt.where(JobListing.city == city)
    if remote_type:
        stmt = stmt.where(JobListing.remote_type == remote_type)
    if source:
        stmt = stmt.where(JobSource.key == source)
    if min_score:
        stmt = stmt.where(JobMatch.score >= min_score)
    if max_experience is not None:
        stmt = stmt.where(or_(JobListing.experience_min.is_(None), JobListing.experience_min <= max_experience))
    if min_salary_lpa is not None:
        stmt = stmt.where(JobListing.salary_currency == "INR", JobListing.salary_max >= min_salary_lpa * 100_000)
    if posted_within_hours:
        stmt = stmt.where(JobListing.posted_at >= utcnow() - timedelta(hours=posted_within_hours))
    if freshness:
        stmt = stmt.where(JobMatch.freshness_bucket == freshness)
    if status:
        stmt = stmt.where(JobMatch.status == status)
    if not include_suspicious:
        stmt = stmt.where(or_(JobMatch.is_suspicious.is_(False), JobMatch.id.is_(None)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {"score": JobMatch.score.desc(), "posted": JobListing.posted_at.desc(),
             "discovered": JobListing.discovered_at.desc()}[sort]
    rows = db.execute(stmt.order_by(order.nulls_last(), JobListing.id.desc())
                      .offset((page - 1) * size).limit(size)).all()
    return JobPage(total=total or 0, items=[_out(j, m) for j, m in rows])


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, db: Session = Depends(get_db), profile: CandidateProfile = Depends(current_profile)):
    job = db.get(JobListing, job_id)
    if not job or job.is_excluded:
        raise HTTPException(404, "Job not found")
    m = db.scalar(select(JobMatch).where(JobMatch.job_id == job_id, JobMatch.profile_id == profile.id))
    return _out(job, m, detail=True)


@router.patch("/{job_id}/status", response_model=MatchOut)
def set_status(job_id: int, body: MatchStatusIn, request: Request, db: Session = Depends(get_db),
               profile: CandidateProfile = Depends(current_profile), user: User = Depends(current_user)):
    m = db.scalar(select(JobMatch).where(JobMatch.job_id == job_id, JobMatch.profile_id == profile.id))
    if not m:
        raise HTTPException(404, "Job has not been scored yet")
    m.status = body.status
    audit(db, request, user, "job.status", "job_listing", job_id, status=body.status)
    db.commit()
    return m
