from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    profile: Mapped["CandidateProfile | None"] = relationship(back_populates="user", uselist=False)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    headline: Mapped[str] = mapped_column(String(255), default="")
    years_experience: Mapped[float] = mapped_column(Float, default=2.0)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    priority_cities: Mapped[list] = mapped_column(JSON, default=list)
    target_countries: Mapped[list] = mapped_column(JSON, default=list)
    salary_min_lpa: Mapped[float] = mapped_column(Float, default=8.0)
    salary_max_lpa: Mapped[float] = mapped_column(Float, default=15.0)
    match_threshold: Mapped[int] = mapped_column(Integer, default=55)
    alert_threshold: Mapped[int] = mapped_column(Integer, default=75)
    resume_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())
    user: Mapped[User] = relationship(back_populates="profile")


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    category: Mapped[str] = mapped_column(String(40), default="other")
    aliases: Mapped[list] = mapped_column(JSON, default=list)


class JobSource(Base):
    __tablename__ = "job_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # ats | api | rss | email
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    min_interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    jobs_found_total: Mapped[int] = mapped_column(Integer, default=0)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("ats_type", "ats_token", name="uq_company_ats"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    ats_type: Mapped[str | None] = mapped_column(String(20))  # greenhouse | lever | ashby
    ats_token: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(60))
    board_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    board_error: Mapped[str | None] = mapped_column(Text)
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class JobListing(Base):
    __tablename__ = "job_listings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_job_source_external"),
        Index("ix_job_active_posted", "is_active", "posted_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("job_sources.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str | None] = mapped_column(String(160), index=True)  # e.g. greenhouse:stripe
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("job_listings.id"))
    title: Mapped[str] = mapped_column(String(300))
    company_name: Mapped[str] = mapped_column(String(200), index=True)
    location: Mapped[str] = mapped_column(String(300), default="")
    country: Mapped[str | None] = mapped_column(String(60), index=True)
    city: Mapped[str | None] = mapped_column(String(80), index=True)
    remote_type: Mapped[str] = mapped_column(String(10), default="unknown")
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(8))
    salary_period: Mapped[str | None] = mapped_column(String(10))
    experience_min: Mapped[float | None] = mapped_column(Float)
    experience_max: Mapped[float | None] = mapped_column(Float)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = _ts(index=True)
    last_seen_at: Mapped[datetime] = _ts()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[JobSource] = relationship()
    match: Mapped[list["JobMatch"]] = relationship(back_populates="job")


class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("job_id", "profile_id", name="uq_match_job_profile"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_listings.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    score: Mapped[float] = mapped_column(Float, index=True)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    matched_skills: Mapped[list] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    freshness_bucket: Mapped[str] = mapped_column(String(10), default="unknown")
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    suspicious_reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new|shortlisted|dismissed
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    job: Mapped[JobListing] = relationship(back_populates="match")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("channel", "dedupe_key", name="uq_notification_dedupe"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(20))  # email | telegram
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|sent|failed|skipped
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (Index("ix_exec_agent_started", "agent", "started_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(40))
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")
    status: Mapped[str] = mapped_column(String(10), default="running")  # running|success|partial|failed
    started_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class SystemConfig(Base):
    __tablename__ = "system_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_created", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()


# ───────────────────────────── Phase 2+ ─────────────────────────────

class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    file_data: Mapped[bytes] = mapped_column(LargeBinary)
    text: Mapped[str] = mapped_column(Text, default="")
    sections: Mapped[dict] = mapped_column(JSON, default=dict)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class Application(Base):
    """One per (profile, job). status = approval flow; stage = CRM/Kanban column."""
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("profile_id", "job_id", name="uq_application_profile_job"),
                      Index("ix_application_stage", "profile_id", "stage"))
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    job_id: Mapped[int] = mapped_column(ForeignKey("job_listings.id"), index=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="prepared")  # prepared|approved|submitted|rejected
    stage: Mapped[str] = mapped_column(String(20), default="prepared")
    resume_variant: Mapped[str] = mapped_column(String(10), default="A")
    apply_method: Mapped[str] = mapped_column(String(20), default="manual")  # autofill|manual
    form_fields: Mapped[list] = mapped_column(JSON, default=list)
    match_score: Mapped[float | None] = mapped_column(Float)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_ref: Mapped[str | None] = mapped_column(String(255))
    confirmation_source: Mapped[str | None] = mapped_column(String(40))  # email|portal|user_attested
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())
    job: Mapped[JobListing] = relationship()
    documents: Mapped[list["ApplicationDocument"]] = relationship(back_populates="application",
                                                                  cascade="all, delete-orphan")


class ApplicationDocument(Base):
    __tablename__ = "application_documents"
    __table_args__ = (UniqueConstraint("application_id", "kind", name="uq_appdoc_kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # resume | cover_letter
    content: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(20), default="template")  # template|llm|edited
    created_at: Mapped[datetime] = _ts()
    application: Mapped[Application] = relationship(back_populates="documents")


class Recruiter(Base):
    """A person: recruiter, hiring manager, or one of the user's own connections (referral finder)."""
    __tablename__ = "recruiters"
    __table_args__ = (UniqueConstraint("profile_id", "name", "company_name", name="uq_recruiter_person"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    company_name: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str | None] = mapped_column(String(320))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    # recruiter | hiring_manager | connection
    relationship_type: Mapped[str] = mapped_column(String(20), default="recruiter")
    source: Mapped[str] = mapped_column(String(30), default="manual")  # manual|linkedin_csv|company_page
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"
    __table_args__ = (UniqueConstraint("recruiter_id", "job_id", "channel", "sequence", name="uq_outreach_once"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("recruiters.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job_listings.id"))
    channel: Mapped[str] = mapped_column(String(20))  # linkedin_note|email|referral_request|follow_up
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|sent|replied|rejected
    generated_by: Mapped[str] = mapped_column(String(20), default="template")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()
    recruiter: Mapped[Recruiter] = relationship()


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # screening|technical|hr|managerial
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|done|cancelled
    outcome: Mapped[str] = mapped_column(String(20), default="pending")  # pending|passed|failed
    notes: Mapped[str] = mapped_column(Text, default="")
    prep_pack: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), unique=True)
    ctc: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    details: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="received")  # received|negotiating|accepted|declined
    received_at: Mapped[datetime] = _ts()


class CompanySignal(Base):
    """Hiring-signal radar: funding news etc."""
    __tablename__ = "company_signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="funding")
    company_name: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    source: Mapped[str] = mapped_column(String(60))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = _ts()


class LLMCache(Base):
    """Every LLM response is cached by a hash of (model, purpose, prompt) — never pay twice."""
    __tablename__ = "llm_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(80))
    response: Mapped[dict] = mapped_column(JSON)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _ts(index=True)
