from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.matching.scorer import DEFAULT_WEIGHTS, score_job
from app.core.timeutil import utcnow
from app.models import CandidateProfile, JobListing, JobMatch, SystemConfig

WEIGHTS_KEY = "matching.weights"


def get_weights(db: Session) -> dict:
    cfg = db.scalar(select(SystemConfig).where(SystemConfig.key == WEIGHTS_KEY))
    return {**DEFAULT_WEIGHTS, **(cfg.value if cfg else {})}


def get_boosts(db: Session) -> dict:
    cfg = db.scalar(select(SystemConfig).where(SystemConfig.key == "matching.boosts"))
    return cfg.value if cfg else {}


RERANK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["fit", "why", "red_flags"],
                 "properties": {"fit": {"type": "integer", "minimum": 0, "maximum": 100},
                                "why": {"type": "string"}, "red_flags": {"type": "string"}}}


def llm_rerank(db: Session, profile, matches: list[JobMatch]) -> int:
    """Layer 3: only the top-N fresh rule-scored jobs go to the LLM (cached), blended 70/30 with rules."""
    from app import llm
    if not llm.available():
        return 0
    n = 0
    skills = ", ".join(profile.skills or [])
    for m in matches:
        if (m.breakdown or {}).get("llm") is not None:
            continue
        j = m.job
        try:
            out = llm.complete_json(
                db, purpose="rerank", schema=RERANK_SCHEMA, effort="low", max_tokens=800,
                system="Rate job fit for a candidate. Be strict about seniority, visa/location and stack. "
                       "'why' is one sentence; 'red_flags' is empty if none.",
                prompt=f"Candidate: ~{profile.years_experience} yrs, India-based. Skills: {skills}. "
                       f"Targets: {', '.join(profile.target_roles or [])}.\n"
                       f"Job: {j.title} | {j.company_name} | {j.location} | {j.remote_type}\n{j.description[:2500]}")
        except llm.LLMUnavailable:
            break
        m.breakdown = {**(m.breakdown or {}), "llm": out["fit"], "rule": m.score}
        m.score = round(0.7 * m.score + 0.3 * out["fit"], 1)
        m.explanation = f"{out['why']} | {m.explanation}" + (f" | ⚠ {out['red_flags']}" if out["red_flags"] else "")
        n += 1
    db.commit()
    return n


def run_matching(db: Session, rescore: bool = False) -> dict:
    """Score every active, non-excluded, non-duplicate job that has no match yet for each profile."""
    weights = get_weights(db)
    boosts = get_boosts(db)
    stats = {"scored": 0, "high": 0, "llm_reranked": 0}
    for profile in db.scalars(select(CandidateProfile)):
        q = (select(JobListing)
             .where(JobListing.is_active.is_(True), JobListing.is_excluded.is_(False),
                    JobListing.duplicate_of_id.is_(None)))
        if not rescore:
            scored = select(JobMatch.job_id).where(JobMatch.profile_id == profile.id)
            q = q.where(JobListing.id.not_in(scored))
        existing = ({m.job_id: m for m in db.scalars(select(JobMatch).where(JobMatch.profile_id == profile.id))}
                    if rescore else {})
        for job in db.scalars(q).all():
            r = score_job(job, profile, weights, boosts)
            m = existing.get(job.id)
            if m is None:
                m = JobMatch(job_id=job.id, profile_id=profile.id)
                db.add(m)
            m.score, m.breakdown = r.score, r.breakdown
            m.matched_skills, m.missing_skills = r.matched_skills, r.missing_skills
            m.explanation, m.freshness_bucket = r.explanation, r.freshness_bucket
            m.is_suspicious, m.suspicious_reasons = r.is_suspicious, r.suspicious_reasons
            stats["scored"] += 1
            if r.score >= profile.alert_threshold and not r.is_suspicious:
                stats["high"] += 1
            if stats["scored"] % 1000 == 0:
                db.flush()
        db.commit()
        from app.core.config import get_settings
        top = db.scalars(select(JobMatch).join(JobListing, JobListing.id == JobMatch.job_id)
                         .where(JobMatch.profile_id == profile.id, JobMatch.alerted_at.is_(None),
                                JobMatch.is_suspicious.is_(False), JobMatch.score >= profile.match_threshold,
                                JobMatch.freshness_bucket.in_(["24h", "7d"]), JobListing.is_active.is_(True))
                         .order_by(JobMatch.score.desc()).limit(get_settings().llm_rerank_top_n)).all()
        stats["llm_reranked"] += llm_rerank(db, profile, top)
    return stats


def skill_gaps(db: Session, profile_id: int, days: int = 14, min_score: float = 45, top: int = 15) -> dict:
    """Skill-gap radar: which skills do *relevant* recent jobs ask for that the profile lacks?"""
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(JobMatch.missing_skills, JobMatch.matched_skills)
        .join(JobListing, JobListing.id == JobMatch.job_id)
        .where(JobMatch.profile_id == profile_id, JobMatch.score >= min_score,
               JobListing.discovered_at >= since, JobListing.is_excluded.is_(False))
    ).all()
    missing, matched = Counter(), Counter()
    for miss, have in rows:
        missing.update(miss or [])
        matched.update(have or [])
    n = len(rows) or 1
    return {
        "jobs_analysed": len(rows),
        "missing": [{"skill": s, "jobs": c, "pct": round(100 * c / n)} for s, c in missing.most_common(top)],
        "strengths": [{"skill": s, "jobs": c, "pct": round(100 * c / n)} for s, c in matched.most_common(10)],
    }
