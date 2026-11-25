"""Agent 5: CRM, reminders, analytics, outcome-driven optimisation and interview prep."""
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import llm
from app.agents.application.service import role_family
from app.core.timeutil import utcnow
from app.models import (
    Application,
    Interview,
    JobListing,
    JobMatch,
    JobSource,
    Offer,
    OutreachMessage,
    SystemConfig,
)
from app.notifications import notify

STAGES = ["prepared", "applied", "screening", "technical", "hr", "offer", "hired", "rejected", "withdrawn"]
RESPONDED = {"screening", "technical", "hr", "offer", "hired"}
INTERVIEWED = {"technical", "hr", "offer", "hired"}
BOOSTS_KEY = "matching.boosts"


def set_stage(db: Session, app: Application, stage: str) -> Application:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    if stage not in ("prepared", "withdrawn") and app.status != "submitted":
        raise ValueError("Only submitted applications can move past 'prepared' (no fabricated progress)")
    app.stage = stage
    if stage in RESPONDED | {"rejected", "withdrawn"}:
        app.follow_up_at = None
    db.commit()
    return app


def send_reminders(db: Session) -> dict:
    """Follow-up reminders (applications with no response) — one digest per day."""
    now = utcnow()
    due = db.execute(select(Application, JobListing).join(JobListing, JobListing.id == Application.job_id)
                     .where(Application.follow_up_at.is_not(None), Application.follow_up_at <= now,
                            Application.stage == "applied")).all()
    if not due:
        return {"due": 0}
    lines = [f"- {j.title} @ {j.company_name} (applied {a.submitted_at:%d %b}) → follow up or ping a referral"
             for a, j in due]
    notify(db, kind="follow_up", title=f"Hirenza: {len(due)} follow-up(s) due today", text="\n".join(lines),
           dedupe_key=f"followup:{now:%Y-%m-%d}")
    return {"due": len(due)}


def _rate(num: int, den: int) -> float:
    return round(100 * num / den, 1) if den else 0.0


def analytics(db: Session, profile_id: int, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    apps = db.execute(select(Application, JobListing, JobSource.key)
                      .join(JobListing, JobListing.id == Application.job_id)
                      .join(JobSource, JobSource.id == JobListing.source_id)
                      .where(Application.profile_id == profile_id)).all()
    submitted = [(a, j, s) for a, j, s in apps if a.status == "submitted"]

    def group(keyfn):
        g: dict[str, Counter] = defaultdict(Counter)
        for a, j, s in submitted:
            c = g[keyfn(a, j, s)]
            c["applied"] += 1
            c["responded"] += a.stage in RESPONDED
            c["interviews"] += a.stage in INTERVIEWED
            c["offers"] += a.stage in {"offer", "hired"}
        return [{"key": k, **c, "response_rate": _rate(c["responded"], c["applied"])} for k, c in
                sorted(g.items(), key=lambda kv: -kv[1]["applied"])]

    daily: dict[str, Counter] = defaultdict(Counter)
    for d, n in db.execute(select(func.date(JobListing.discovered_at), func.count())
                           .where(JobListing.discovered_at >= since).group_by(func.date(JobListing.discovered_at))):
        daily[str(d)]["discovered"] = n
    for a, _, _ in submitted:
        if a.submitted_at and a.submitted_at.replace(tzinfo=None) >= since.replace(tzinfo=None):
            daily[a.submitted_at.strftime("%Y-%m-%d")]["applied"] += 1
    stage_counts = Counter(a.stage for a, _, _ in apps)
    msgs = db.execute(select(OutreachMessage.status, func.count()).group_by(OutreachMessage.status)).all()
    out = dict(msgs)
    n_sub = len(submitted)
    return {
        "funnel": {s: stage_counts.get(s, 0) for s in STAGES},
        "totals": {
            "prepared": sum(1 for a, _, _ in apps if a.status == "prepared"),
            "approved_pending_submit": sum(1 for a, _, _ in apps if a.status == "approved"),
            "submitted": n_sub,
            "response_rate": _rate(sum(a.stage in RESPONDED for a, _, _ in submitted), n_sub),
            "interview_rate": _rate(sum(a.stage in INTERVIEWED for a, _, _ in submitted), n_sub),
            "offers": db.scalar(select(func.count(Offer.id))) or 0,
            "interviews": db.scalar(select(func.count(Interview.id))) or 0,
            "outreach_sent": out.get("sent", 0) + out.get("replied", 0),
            "outreach_replied": out.get("replied", 0),
            "outreach_reply_rate": _rate(out.get("replied", 0), out.get("sent", 0) + out.get("replied", 0)),
        },
        "by_source": group(lambda a, j, s: s),
        "by_role_family": group(lambda a, j, s: role_family(j.title)),
        "by_resume_variant": group(lambda a, j, s: a.resume_variant),
        "by_company": group(lambda a, j, s: j.company_name)[:20],
        "daily": [{"date": d, **c} for d, c in sorted(daily.items())],
    }


def optimise(db: Session, profile_id: int, min_samples: int = 5) -> dict:
    """Learn small ranking boosts (±8 pts) from real outcomes, smoothed toward the overall rate."""
    a = analytics(db, profile_id, days=90)
    total = a["totals"]["submitted"]
    if total < min_samples:
        return {"updated": False, "reason": f"need ≥{min_samples} submitted applications (have {total})"}
    base = a["totals"]["response_rate"] / 100
    prior = 5

    def boosts(rows):
        out = {}
        for r in rows:
            smoothed = (r["responded"] + prior * base) / (r["applied"] + prior)
            out[r["key"]] = round(max(-8.0, min(8.0, (smoothed - base) * 40)), 1)
        return out

    value = {"source": boosts(a["by_source"]), "family": boosts(a["by_role_family"]), "samples": total}
    cfg = db.scalar(select(SystemConfig).where(SystemConfig.key == BOOSTS_KEY)) or SystemConfig(key=BOOSTS_KEY)
    cfg.value = value
    db.add(cfg)
    db.commit()
    return {"updated": True, **value}


PREP_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["questions", "stories", "ask_them"],
               "properties": {
                   "questions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                            "required": ["q", "hint"],
                                                            "properties": {"q": {"type": "string"},
                                                                           "hint": {"type": "string"}}}},
                   "stories": {"type": "array", "items": {"type": "string"}},
                   "ask_them": {"type": "array", "items": {"type": "string"}}}}

QUESTION_BANK = {
    "Kubernetes": ["Walk through what happens when you `kubectl apply` a Deployment.",
                   "A pod is in CrashLoopBackOff — how do you debug it?",
                   "Requests vs limits, and how HPA decides to scale."],
    "Terraform": ["How do you manage state and locking for a team?", "Explain modules vs workspaces.",
                  "How do you handle drift?"],
    "AWS": ["Design a VPC for EKS: subnets, NAT, security groups.", "IRSA / pod identity — why and how?"],
    "Docker": ["How do you make an image smaller and safer?", "Multi-stage builds — when and why?"],
    "CI/CD": ["Design a pipeline from commit to prod with security gates.", "How do you do safe rollbacks?"],
    "DevSecOps": ["Where do SAST, SCA and image scanning fit, and how do you avoid blocking devs?"],
    "Python": ["GIL implications for a web service.", "How would you profile a slow Django endpoint?"],
    "Django": ["N+1 queries — detect and fix.", "How do Django migrations work in a CI/CD flow?"],
    "Linux": ["A server is slow — your first 5 commands?", "Explain load average."],
    "Prometheus": ["Pull vs push monitoring; what would you alert on for an API?"],
    "Helm": ["How do you structure values for multiple environments?"],
    "ArgoCD": ["GitOps vs push-based CD — trade-offs?"],
}


def interview_prep(db: Session, interview: Interview, app: Application, resume_text: str) -> str:
    job = app.job
    match = db.scalar(select(JobMatch).where(JobMatch.job_id == job.id, JobMatch.profile_id == app.profile_id))
    skills = (match.matched_skills + match.missing_skills) if match else (job.skills or [])
    if llm.available():
        try:
            out = llm.complete_json(
                db, purpose="interview_prep", schema=PREP_SCHEMA, effort="medium", max_tokens=6000,
                system="You are a senior DevOps/backend interviewer preparing a candidate. Use only facts from "
                       "the resume for STAR stories; flag gaps honestly.",
                prompt=f"Interview type: {interview.kind}\nJob: {job.title} at {job.company_name}\n"
                       f"JD:\n{job.description[:5000]}\n\nRESUME:\n{resume_text[:6000]}\n"
                       "Give 12 likely questions with answer hints, 4 STAR stories mapped to the JD, "
                       "and 4 smart questions to ask them.")
            md = [f"# {interview.kind.title()} prep — {job.title} @ {job.company_name}", "", "## Likely questions"]
            md += [f"- **{q['q']}**\n  - {q['hint']}" for q in out["questions"]]
            md += ["", "## Your stories (STAR)", *[f"- {s}" for s in out["stories"]],
                   "", "## Ask them", *[f"- {s}" for s in out["ask_them"]]]
            return "\n".join(md)
        except llm.LLMUnavailable:
            pass
    md = [f"# {interview.kind.title()} prep — {job.title} @ {job.company_name}", "", "## Likely questions"]
    for s in skills:
        md += [f"- {q}" for q in QUESTION_BANK.get(s, [])]
    if match and match.missing_skills:
        md += ["", "## Gaps to prepare honestly", *[f"- {s}: know the basics + how you'd learn it fast"
                                                    for s in match.missing_skills]]
    md += ["", "## Your stories (STAR)",
           "- MOSIP / OpenG2P deployment on Kubernetes: situation, your actions, measurable result",
           "- Adding SonarQube/Trivy/Snyk gates to CI/CD without slowing developers",
           "- A production incident you debugged with Prometheus/Grafana/SigNoz",
           "- Terraform-provisioned AWS (VPC/EKS/IAM): design choices",
           "", "## Ask them", "- How do you deploy to production today, and what would you change?",
           "- What does on-call look like?", "- What would success look like in my first 90 days?"]
    return "\n".join(md)


def prune(db: Session) -> dict:
    """Keep Neon's free tier small: drop long-closed jobs nobody applied to; trim old low-score text."""
    now = utcnow()
    applied = select(Application.job_id)
    closed = select(JobListing.id).where(JobListing.is_active.is_(False),
                                         JobListing.closed_at < now - timedelta(days=14),
                                         JobListing.id.not_in(applied))
    ids = list(db.scalars(closed))
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        db.execute(update(JobListing).where(JobListing.duplicate_of_id.in_(chunk)).values(duplicate_of_id=None))
        db.execute(update(OutreachMessage).where(OutreachMessage.job_id.in_(chunk)).values(job_id=None))
        db.execute(delete(JobMatch).where(JobMatch.job_id.in_(chunk)))
        db.execute(delete(JobListing).where(JobListing.id.in_(chunk)))
    low = select(JobMatch.job_id).where(JobMatch.score < 40)
    trimmed = db.execute(update(JobListing).where(
        JobListing.discovered_at < now - timedelta(days=21), JobListing.id.in_(low),
        JobListing.id.not_in(applied), func.length(JobListing.description) > 0)
        .values(description="", raw={})).rowcount
    db.commit()
    return {"deleted_closed": len(ids), "trimmed_low_score": trimmed or 0}
