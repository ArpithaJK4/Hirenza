"""Agent 3: application preparation. Never submits — a human approves and submits."""
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.agents.application.resume import tailor
from app.agents.matching.scorer import _FAMILY_RX
from app.core.config import get_settings
from app.core.timeutil import utcnow
from app.guardrails import is_current_employer
from app.models import (
    Application,
    ApplicationDocument,
    CandidateProfile,
    JobListing,
    JobMatch,
    Resume,
)


class ApplicationBlocked(Exception):
    pass


def role_family(title: str) -> str:
    for fam, rx in _FAMILY_RX.items():
        if rx.search(title):
            return fam
    return "other"


def pick_variant(db: Session, profile_id: int, family: str) -> str:
    """Alternate resume variants per role family for A/B testing."""
    rows = db.execute(select(Application.resume_variant, JobListing.title)
                      .join(JobListing, JobListing.id == Application.job_id)
                      .where(Application.profile_id == profile_id)).all()
    counts = {"A": 0, "B": 0}
    for v, t in rows:
        if role_family(t) == family and v in counts:
            counts[v] += 1
    return "A" if counts["A"] <= counts["B"] else "B"


def check_duplicate(db: Session, profile_id: int, job: JobListing) -> None:
    if db.scalar(select(Application.id).where(Application.profile_id == profile_id, Application.job_id == job.id)):
        raise ApplicationBlocked("You already have an application for this job")
    same = db.scalar(select(Application.id).join(JobListing, JobListing.id == Application.job_id)
                     .where(Application.profile_id == profile_id, JobListing.fingerprint == job.fingerprint,
                            Application.status != "rejected"))
    if same:
        raise ApplicationBlocked("Duplicate: you already applied to this role at this company via another source")


def greenhouse_questions(job: JobListing) -> list[dict]:
    """Greenhouse publishes application questions; other ATSs fall back to standard fields."""
    if not (job.scope or "").startswith("greenhouse:"):
        return []
    token = job.scope.split(":", 1)[1]
    try:
        r = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job.external_id}?questions=true",
                      timeout=20)
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    out = []
    for q in r.json().get("questions", []):
        for f in q.get("fields", []):
            out.append({"label": q.get("label"), "name": f.get("name"), "type": f.get("type"),
                        "required": q.get("required", False),
                        "options": [v.get("label") for v in f.get("values", [])][:20]})
    return out


STANDARD_FIELDS = [{"label": n, "name": k, "type": "input_text", "required": True}
                   for k, n in (("first_name", "First name"), ("last_name", "Last name"), ("email", "Email"),
                                ("phone", "Phone"), ("resume", "Resume/CV"))]


def _autofill_values() -> dict:
    s = get_settings()
    first, _, last = (s.candidate_full_name or "").partition(" ")
    return {"first_name": first, "last_name": last, "email": s.candidate_email, "phone": s.candidate_phone,
            "linkedin": s.candidate_linkedin_url, "github": s.candidate_github_url, "location": s.candidate_location}


def _template_cover_letter(job: JobListing, match: JobMatch | None, profile: CandidateProfile) -> str:
    s = get_settings()
    skills = ", ".join((match.matched_skills if match else [])[:6]) or "Python, Docker, Kubernetes and AWS"
    name = s.candidate_full_name or "[Your Name]"
    return f"""Dear Hiring Team at {job.company_name},

I'm applying for the {job.title} role. I work as a DevOps Engineer, building CI/CD pipelines with \
integrated security scanning, running containerised workloads on Kubernetes (AWS EKS and on-prem), and \
provisioning AWS infrastructure with Terraform. Before that I built Python/Django backends and REST APIs.

Your role asks for {skills} — this is the stack I use day to day. On national digital-public-infrastructure \
platforms (MOSIP, OpenG2P, credential issuance) I deployed and operated microservices with Helm, integrated \
SonarQube, Trivy, Snyk and OWASP Dependency-Check into pipelines, and set up Prometheus/Grafana monitoring.

I'd welcome the chance to discuss how I can contribute to {job.company_name}.

Best regards,
{name}
"""


COVER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["cover_letter", "summary"],
                "properties": {"cover_letter": {"type": "string"}, "summary": {"type": "string"}}}
COVER_SYSTEM = ("You write concise, specific job application material for a DevOps/Python engineer. "
                "Use ONLY facts present in the provided resume; never invent employers, metrics, dates, "
                "certifications or skills. Plain text, no markdown headings, under 220 words for the letter. "
                "The summary is a 2-3 sentence resume summary tailored to the job, also using only resume facts.")


def prepare_application(db: Session, profile: CandidateProfile, job_id: int) -> Application:
    job = db.get(JobListing, job_id)
    if not job or not job.is_active:
        raise ApplicationBlocked("Job not found or no longer open")
    if job.is_excluded or is_current_employer(job.company_name, url_or_email=job.url):
        raise ApplicationBlocked("Blocked: this is your current employer")
    check_duplicate(db, profile.id, job)
    resume = db.scalar(select(Resume).where(Resume.profile_id == profile.id)
                       .order_by(Resume.is_default.desc(), Resume.id.desc()))
    if not resume:
        raise ApplicationBlocked("Upload a resume first")
    match = db.scalar(select(JobMatch).where(JobMatch.job_id == job.id, JobMatch.profile_id == profile.id))
    variant = pick_variant(db, profile.id, role_family(job.title))

    sections = dict(resume.sections or {})
    cover, by = _template_cover_letter(job, match, profile), "template"
    if llm.available():
        try:
            out = llm.complete_json(
                db, purpose="cover_letter", system=COVER_SYSTEM, schema=COVER_SCHEMA, effort="medium",
                prompt=f"RESUME:\n{resume.text[:6000]}\n\nJOB: {job.title} at {job.company_name}\n"
                       f"JOB DESCRIPTION:\n{job.description[:4000]}")
            cover, by = out["cover_letter"].strip(), "llm"
            sections["summary"] = out["summary"].strip()
        except llm.LLMUnavailable:
            pass
    resume_md = tailor(sections, resume.skills or [], job.skills or [], variant)

    app = Application(profile_id=profile.id, job_id=job.id, resume_id=resume.id, resume_variant=variant,
                      status="prepared", stage="prepared", match_score=match.score if match else None,
                      apply_method="autofill" if (job.scope or "").split(":")[0] in
                      ("greenhouse", "lever", "ashby") else "manual",
                      form_fields=(greenhouse_questions(job) or STANDARD_FIELDS))
    db.add(app)
    db.flush()
    db.add_all([ApplicationDocument(application_id=app.id, kind="resume", content=resume_md, generated_by=by),
                ApplicationDocument(application_id=app.id, kind="cover_letter", content=cover, generated_by=by)])
    if match:
        match.status = "shortlisted"
    db.commit()
    return app


def approve(db: Session, app: Application) -> Application:
    if app.status != "prepared":
        raise ApplicationBlocked(f"Cannot approve an application in status '{app.status}'")
    if app.job.is_excluded or is_current_employer(app.job.company_name):
        raise ApplicationBlocked("Blocked: current employer")
    app.status, app.approved_at = "approved", utcnow()
    db.commit()
    return app


def reject(db: Session, app: Application, reason: str = "") -> Application:
    if app.status == "submitted":
        raise ApplicationBlocked("Already submitted")
    app.status, app.stage = "rejected", "withdrawn"
    app.notes = (app.notes + f"\nRejected in review: {reason}").strip()
    db.commit()
    return app


def mark_submitted(db: Session, app: Application, confirmation_ref: str, source: str) -> Application:
    """Only after a real submission: the user (or the confirmation email) provides a reference."""
    if app.status != "approved":
        raise ApplicationBlocked("Approve the application before marking it submitted")
    if not confirmation_ref.strip():
        raise ApplicationBlocked("A confirmation reference is required (email subject, portal ID, or screenshot note)")
    now = utcnow()
    app.status, app.stage, app.submitted_at = "submitted", "applied", now
    app.confirmation_ref, app.confirmation_source = confirmation_ref.strip()[:255], source
    app.follow_up_at = now + timedelta(days=get_settings().follow_up_days)
    db.commit()
    return app
