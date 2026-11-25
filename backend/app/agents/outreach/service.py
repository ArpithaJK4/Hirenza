"""Agent 4: outreach drafts, referral finder, hiring signals, proof-of-work. Drafts only — a human
approves, and LinkedIn messages are always sent manually by the user (no LinkedIn automation)."""
import csv
import io
import json
import re
import shutil
import subprocess
from datetime import timedelta

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.agents.discovery.normalize import parse_datetime
from app.core.config import get_settings
from app.core.timeutil import utcnow
from app.guardrails import is_current_employer, normalize_company
from app.models import (
    AuditLog,
    Company,
    CompanySignal,
    JobListing,
    JobMatch,
    OutreachMessage,
    Recruiter,
)
from app.notifications import send_email

LINKEDIN_NOTE_LIMIT = 300


class OutreachBlocked(Exception):
    pass


def guard_person(db: Session, r: Recruiter) -> None:
    if r.is_excluded or is_current_employer(r.company_name, url_or_email=r.email) or \
            is_current_employer(None, url_or_email=r.linkedin_url):
        db.add(AuditLog(action="guardrail.outreach_blocked", entity="recruiter", entity_id=str(r.id),
                        details={"company": r.company_name}))
        db.commit()
        raise OutreachBlocked("Blocked: this person works at your current employer")


def upsert_person(db: Session, profile_id: int, *, name: str, company_name: str, title: str = "",
                  email: str | None = None, linkedin_url: str | None = None, relationship_type: str = "recruiter",
                  source: str = "manual", notes: str = "") -> Recruiter:
    r = db.scalar(select(Recruiter).where(Recruiter.profile_id == profile_id, Recruiter.name == name,
                                          Recruiter.company_name == company_name))
    if r is None:
        r = Recruiter(profile_id=profile_id, name=name[:200], company_name=company_name[:200])
        db.add(r)
    r.title, r.email, r.linkedin_url = title[:200], email or r.email, linkedin_url or r.linkedin_url
    r.relationship_type, r.source, r.notes = relationship_type, source, notes or r.notes
    norm = normalize_company(company_name)
    c = db.scalar(select(Company).where(Company.normalized_name == norm)) if norm else None
    r.company_id = c.id if c else None
    r.is_excluded = is_current_employer(company_name, url_or_email=email)
    return r


def import_linkedin_connections(db: Session, profile_id: int, data: bytes) -> dict:
    """Parse LinkedIn's own 'Connections.csv' data export (Settings → Data privacy → Get a copy of your data)."""
    text = data.decode("utf-8-sig", "replace")
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("First Name")), None)
    if start is None:
        raise OutreachBlocked("Not a LinkedIn Connections.csv export (missing 'First Name' header)")
    added = excluded = 0
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        name = f"{row.get('First Name', '').strip()} {row.get('Last Name', '').strip()}".strip()
        company = (row.get("Company") or "").strip()
        if not name or not company:
            continue
        r = upsert_person(db, profile_id, name=name, company_name=company, title=row.get("Position") or "",
                          email=(row.get("Email Address") or None), linkedin_url=row.get("URL") or None,
                          relationship_type="connection", source="linkedin_csv")
        added += 1
        excluded += r.is_excluded
    db.commit()
    return {"imported": added, "excluded_current_employer": excluded}


def referral_suggestions(db: Session, profile_id: int, min_score: float = 65, limit: int = 30) -> list[dict]:
    """Referral finder: your connections who work at companies with your best open matches."""
    rows = db.execute(
        select(JobMatch, JobListing).join(JobListing, JobListing.id == JobMatch.job_id)
        .where(JobMatch.profile_id == profile_id, JobMatch.score >= min_score, JobMatch.is_suspicious.is_(False),
               JobListing.is_active.is_(True), JobListing.is_excluded.is_(False))
        .order_by(JobMatch.score.desc()).limit(500)).all()
    by_company: dict[str, list] = {}
    for m, j in rows:
        by_company.setdefault(normalize_company(j.company_name), []).append((m, j))
    people = db.scalars(select(Recruiter).where(Recruiter.profile_id == profile_id,
                                                Recruiter.relationship_type == "connection",
                                                Recruiter.is_excluded.is_(False))).all()
    out = []
    for p in people:
        jobs = by_company.get(normalize_company(p.company_name))
        if jobs:
            out.append({"recruiter_id": p.id, "name": p.name, "title": p.title, "company": p.company_name,
                        "linkedin_url": p.linkedin_url,
                        "jobs": [{"job_id": j.id, "title": j.title, "score": m.score} for m, j in jobs[:3]]})
    out.sort(key=lambda x: -x["jobs"][0]["score"])
    return out[:limit]


def _templates(kind: str, r: Recruiter, job: JobListing | None, sequence: int) -> tuple[str, str]:
    first = r.name.split()[0] if r.name else "there"
    role = job.title if job else "DevOps / Platform / Python backend roles"
    co = r.company_name or (job.company_name if job else "your company")
    name = get_settings().candidate_full_name or "[Your Name]"
    if kind == "linkedin_note":
        body = (f"Hi {first}, I'm a DevOps engineer (K8s/EKS, Terraform, CI/CD with DevSecOps) interested in "
                f"the {role} role at {co}. Would love to connect and learn about the team.")
        return "", body[:LINKEDIN_NOTE_LIMIT]
    if kind == "referral_request":
        return f"Referral for {role} at {co}?", (
            f"Hi {first},\n\nHope you're doing well! I noticed {co} is hiring for {role}"
            f"{' (' + job.url + ')' if job else ''}. I work as a DevOps engineer — Kubernetes on AWS EKS and "
            f"on-prem, Terraform, GitHub Actions/Jenkins pipelines with SonarQube/Trivy/Snyk — plus Python "
            f"backend experience.\n\nWould you be comfortable referring me, or telling me a bit about the team? "
            f"Happy to share my resume. No worries at all if not.\n\nThanks,\n{name}")
    if kind == "follow_up":
        return f"Following up: {role}", (
            f"Hi {first},\n\nJust following up on my note about the {role} role at {co}. I'm still very "
            f"interested and happy to share anything that helps.\n\nThanks,\n{name}")
    return f"{role} at {co} — DevOps engineer", (
        f"Hi {first},\n\nI'm reaching out about the {role} opening at {co}. I'm a DevOps engineer working "
        f"with Kubernetes (EKS + on-prem), Terraform on AWS, and CI/CD pipelines with integrated security "
        f"scanning, with a Python/Django backend background.\n\nWould you be open to a short chat about the "
        f"role? I can share my resume right away.\n\nBest,\n{name}")


DRAFT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["subject", "body"],
                "properties": {"subject": {"type": "string"}, "body": {"type": "string"}}}


def create_draft(db: Session, r: Recruiter, kind: str, job: JobListing | None = None,
                 extra_context: str = "") -> OutreachMessage:
    guard_person(db, r)
    if job and (job.is_excluded or is_current_employer(job.company_name)):
        raise OutreachBlocked("Blocked: current employer")
    prev = db.scalars(select(OutreachMessage).where(
        OutreachMessage.recruiter_id == r.id, OutreachMessage.job_id == (job.id if job else None),
        OutreachMessage.channel == kind)).all()
    if prev and kind != "follow_up":
        raise OutreachBlocked("A message of this type to this person for this job already exists")
    sequence = len(prev) + 1
    subject, body = _templates(kind, r, job, sequence)
    by = "template"
    if llm.available() and kind != "follow_up":
        try:
            limit = f"Body MUST be under {LINKEDIN_NOTE_LIMIT} characters. " if kind == "linkedin_note" else ""
            out = llm.complete_json(
                db, purpose=f"outreach_{kind}", schema=DRAFT_SCHEMA, effort="low", max_tokens=1500,
                system="You write short, warm, specific outreach for a DevOps/Python engineer. No flattery, "
                       "no invented facts, no pressure. " + limit,
                prompt=f"Type: {kind}\nRecipient: {r.name}, {r.title} at {r.company_name} "
                       f"({r.relationship_type})\nJob: {job.title if job else '-'}\n"
                       f"Job summary: {(job.description[:1200] if job else '')}\n"
                       f"Context: {extra_context}\nTemplate to improve:\nSubject: {subject}\n{body}")
            subject, body, by = out["subject"], out["body"], "llm"
        except llm.LLMUnavailable:
            pass
    if kind == "linkedin_note":
        body = body[:LINKEDIN_NOTE_LIMIT]
    msg = OutreachMessage(recruiter_id=r.id, job_id=job.id if job else None, channel=kind, sequence=sequence,
                          subject=subject, body=body, generated_by=by)
    db.add(msg)
    db.commit()
    return msg


def approve_message(db: Session, msg: OutreachMessage) -> OutreachMessage:
    guard_person(db, msg.recruiter)
    if msg.status != "draft":
        raise OutreachBlocked(f"Message is already {msg.status}")
    msg.status, msg.approved_at = "approved", utcnow()
    db.commit()
    return msg


def send_message(db: Session, msg: OutreachMessage) -> OutreachMessage:
    """Email is sent via your SMTP after approval. LinkedIn notes are never sent by the system."""
    guard_person(db, msg.recruiter)
    if msg.status != "approved":
        raise OutreachBlocked("Approve the message before sending")
    if msg.channel == "linkedin_note":
        raise OutreachBlocked("LinkedIn messages are never automated: copy the text, send it yourself, "
                              "then use 'mark sent'")
    if not msg.recruiter.email:
        raise OutreachBlocked("No email address for this person — send manually and use 'mark sent'")
    send_email(msg.subject, msg.body, to=msg.recruiter.email)
    msg.status, msg.sent_at = "sent", utcnow()
    db.commit()
    return msg


def mark_sent(db: Session, msg: OutreachMessage) -> OutreachMessage:
    if msg.status != "approved":
        raise OutreachBlocked("Approve the message first")
    msg.status, msg.sent_at = "sent", utcnow()
    db.commit()
    return msg


FUNDING_RX = re.compile(r"\b(raises?|raised|secures?|bags?|funding|series [a-e]|seed round|pre-series)\b", re.I)
COMPANY_RX = re.compile(r"^([A-Z][\w.&'-]*(?:\s+[A-Z][\w.&'-]*){0,3})\s+(?:raises?|raised|secures?|bags?)\b")


def refresh_signals(db: Session) -> dict:
    """Hiring-signal radar: freshly funded companies usually hire infra/backend engineers within weeks."""
    added = 0
    for url in get_settings().signal_feeds:
        try:
            r = httpx.get(url, timeout=20, follow_redirects=True,
                          headers={"User-Agent": get_settings().http_user_agent})
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        for e in feedparser.parse(r.text).entries:
            title, link = e.get("title", ""), e.get("link", "")
            if not link or not FUNDING_RX.search(title):
                continue
            if db.scalar(select(CompanySignal.id).where(CompanySignal.url == link)):
                continue
            m = COMPANY_RX.search(title)
            company = m.group(1) if m else ""
            if company and is_current_employer(company):
                continue
            published = parse_datetime(e.get("published")) if e.get("published") else None
            db.add(CompanySignal(kind="funding", company_name=company, title=title[:500], url=link[:1000],
                                 source=url.split("/")[2], published_at=published or utcnow()))
            added += 1
    cutoff = utcnow() - timedelta(days=60)
    for old in db.scalars(select(CompanySignal).where(CompanySignal.created_at < cutoff)):
        db.delete(old)
    db.commit()
    return {"added": added}


def proof_of_work_scan(image: str) -> dict:
    """Run Trivy on a PUBLIC container image the user names. Read-only, public data only."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9._/:@-]{1,200}", image):
        raise OutreachBlocked("Invalid image reference")
    trivy = shutil.which("trivy")
    if not trivy:
        raise OutreachBlocked("Trivy is not installed (brew install trivy)")
    proc = subprocess.run([trivy, "image", "--quiet", "--format", "json", "--severity", "HIGH,CRITICAL",  # noqa: S603
                           "--ignore-unfixed", image], capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode != 0:
        raise OutreachBlocked(f"Trivy failed: {proc.stderr[:300]}")
    data = json.loads(proc.stdout or "{}")
    vulns = [v for res in data.get("Results", []) for v in res.get("Vulnerabilities") or []]
    top = sorted(vulns, key=lambda v: v.get("Severity") != "CRITICAL")[:5]
    return {"image": image, "high_critical_fixable": len(vulns),
            "critical": sum(v.get("Severity") == "CRITICAL" for v in vulns),
            "top": [{"id": v.get("VulnerabilityID"), "pkg": v.get("PkgName"), "fixed": v.get("FixedVersion"),
                     "severity": v.get("Severity")} for v in top],
            "note_draft": (f"I ran Trivy against your public image {image} and noticed {len(vulns)} fixable "
                           f"HIGH/CRITICAL findings (e.g. {', '.join(v['VulnerabilityID'] for v in top[:2])}). "
                           "Most clear up by bumping the base image — happy to share the details or a PR.")
            if vulns else f"Your public image {image} looks clean on Trivy HIGH/CRITICAL — nice work."}
