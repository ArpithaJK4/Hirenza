"""Speed alerts: one digest email per run with every new high match, freshest first."""
import html as h

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import utcnow
from app.models import CandidateProfile, JobListing, JobMatch
from app.notifications import email_configured, notify, telegram_configured

_FRESH_ORDER = {"24h": 0, "7d": 1, "unknown": 2, "older": 3}


def _salary(job: JobListing) -> str:
    if job.salary_min is None and job.salary_max is None:
        return ""
    if job.salary_currency == "INR":
        lo = f"{(job.salary_min or 0) / 1e5:.0f}" if job.salary_min else "?"
        hi = f"{(job.salary_max or 0) / 1e5:.0f}" if job.salary_max else "?"
        return f"₹{lo}-{hi} LPA"
    return f"{job.salary_currency or ''} {int(job.salary_min or 0):,}-{int(job.salary_max or 0):,}".strip()


def send_job_alerts(db: Session) -> dict:
    if not (email_configured() or telegram_configured()):
        return {"alerted": 0, "reason": "no notification channel configured"}
    limit = get_settings().max_alerts_per_run
    total = 0
    for profile in db.scalars(select(CandidateProfile)):
        rows = db.execute(
            select(JobMatch, JobListing).join(JobListing, JobListing.id == JobMatch.job_id)
            .where(JobMatch.profile_id == profile.id, JobMatch.alerted_at.is_(None),
                   JobMatch.score >= profile.alert_threshold, JobMatch.is_suspicious.is_(False),
                   JobMatch.status != "dismissed", JobMatch.freshness_bucket != "older",
                   JobListing.is_active.is_(True), JobListing.is_excluded.is_(False))
        ).all()
        if not rows:
            continue
        rows.sort(key=lambda r: (_FRESH_ORDER.get(r[0].freshness_bucket, 9), -r[0].score))
        top = rows[:limit]
        lines, items, tg = [], [], []
        for m, j in top:
            fire = "🔥" if m.freshness_bucket == "24h" else "⭐"
            sal = _salary(j)
            head = f"{fire} {m.score:.0f}% · {j.title} · {j.company_name} · {j.city or j.location or j.country}"
            lines.append(f"{head}{' · ' + sal if sal else ''}\n   {m.explanation}\n   {j.apply_url or j.url}\n")
            items.append(
                f"<tr><td style='padding:10px 0;border-bottom:1px solid #eee'>"
                f"<div style='font-size:15px'><b>{fire} {m.score:.0f}%</b> · "
                f"<a href='{h.escape(j.apply_url or j.url)}'>{h.escape(j.title)}</a></div>"
                f"<div style='color:#333'>{h.escape(j.company_name)} · {h.escape(j.city or j.location or '')}"
                f"{' · ' + h.escape(sal) if sal else ''} · via {h.escape(j.source.name)}</div>"
                f"<div style='color:#666;font-size:13px'>{h.escape(m.explanation)}</div></td></tr>")
            tg.append(f"{fire} <b>{m.score:.0f}%</b> <a href='{h.escape(j.apply_url or j.url)}'>"
                      f"{h.escape(j.title)}</a> · {h.escape(j.company_name)}")
        more = len(rows) - len(top)
        title = f"Hirenza: {len(top)} new matching job{'s' if len(top) > 1 else ''}" + \
                (f" (+{more} more)" if more > 0 else "")
        html = ("<div style='font-family:system-ui,sans-serif;max-width:680px'>"
                "<p>Freshest first. Apply to 🔥 jobs today — early applicants get seen.</p>"
                f"<table style='width:100%;border-collapse:collapse'>{''.join(items)}</table></div>")
        key = f"job-digest:{profile.id}:{','.join(str(m.id) for m, _ in top)}"
        notify(db, kind="job_alert", title=title, text="\n".join(lines), html=html,
               telegram_text=f"<b>{h.escape(title)}</b>\n" + "\n".join(tg), dedupe_key=key[:200],
               user_id=profile.user_id)
        now = utcnow()
        for m, _ in top:
            m.alerted_at = now
        db.commit()
        total += len(top)
    return {"alerted": total}


def notify_failing_sources(db: Session, keys: list[str]) -> None:
    if not keys:
        return
    day = utcnow().strftime("%Y-%m-%d")
    notify(db, kind="source_failure", title=f"Hirenza: job sources failing ({', '.join(keys)})",
           text="These sources failed 3+ runs in a row. Check `hirenza sources` or the logs.",
           dedupe_key=f"source-fail:{day}:{','.join(sorted(keys))}")
