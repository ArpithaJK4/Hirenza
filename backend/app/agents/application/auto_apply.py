"""Rule-based auto-apply for PUBLIC company ATS forms (Greenhouse / Lever / Ashby) only.

Turning the rule on (AUTO_APPLY_ENABLED) is the user's standing approval for jobs that match it.
Never: login-based job sites, CAPTCHAs, current employer, duplicates, scams, guessed answers.
Dry-run (default) fills the form and screenshots it without submitting.
"""
import logging
import re
import tempfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.application import service as app_svc
from app.agents.application.forms import answers_for, fill_page
from app.agents.application.resume import render_pdf
from app.core.config import BASE_DIR, get_settings
from app.core.timeutil import utcnow
from app.guardrails import is_current_employer
from app.models import Application, CandidateProfile, JobListing, JobMatch, SystemConfig
from app.notifications import notify

log = logging.getLogger(__name__)
SHOTS = BASE_DIR / "data" / "screenshots"
PAUSE_KEY = "auto_apply.paused"
ATS = ("greenhouse", "lever", "ashby")
CONFIRM = re.compile(r"thank(s| you)|application (has been |was )?(received|submitted)|we('| ha)ve received|"
                     r"successfully (submitted|applied)", re.I)
SUBMIT_SELECTORS = ["button:has-text('Submit application')", "button:has-text('Submit Application')",
                    "button[type=submit]", "input[type=submit]", "button:has-text('Submit')"]


def is_paused(db: Session) -> bool:
    cfg = db.scalar(select(SystemConfig).where(SystemConfig.key == PAUSE_KEY))
    return bool(cfg and cfg.value.get("paused"))


def set_paused(db: Session, paused: bool) -> None:
    cfg = db.scalar(select(SystemConfig).where(SystemConfig.key == PAUSE_KEY)) or SystemConfig(key=PAUSE_KEY)
    cfg.value = {"paused": paused}
    db.add(cfg)
    db.commit()


def used_today(db: Session, profile_id: int) -> int:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count(Application.id)).where(
        Application.profile_id == profile_id, Application.apply_method == "auto",
        Application.created_at >= start)) or 0


def candidates(db: Session, profile: CandidateProfile, limit: int) -> list[JobListing]:
    s = get_settings()
    applied = select(Application.job_id).where(Application.profile_id == profile.id)
    rows = db.execute(
        select(JobListing).join(JobMatch, JobMatch.job_id == JobListing.id)
        .where(JobMatch.profile_id == profile.id, JobMatch.score >= s.auto_apply_min_score,
               JobMatch.is_suspicious.is_(False), JobMatch.status != "dismissed",
               JobMatch.freshness_bucket.in_(["24h", "7d"]), JobListing.is_active.is_(True),
               JobListing.is_excluded.is_(False), JobListing.duplicate_of_id.is_(None),
               JobListing.id.not_in(applied))
        .order_by(JobMatch.freshness_bucket, JobMatch.score.desc()).limit(limit * 5)).scalars().all()
    out = []
    for j in rows:
        ats = (j.scope or "").split(":")[0]
        if ats not in ATS or is_current_employer(j.company_name, url_or_email=j.url):
            continue
        if j.country not in s.auto_apply_countries and not (j.remote_type == "remote" and "Worldwide"
                                                           in s.auto_apply_countries and j.country is None):
            continue
        out.append(j)
        if len(out) >= limit:
            break
    return out


def _apply_url(job: JobListing) -> str:
    url = job.apply_url or job.url
    if job.scope and job.scope.startswith("greenhouse:"):
        # the hosted Greenhouse form (company sites often embed it in an iframe)
        token = job.scope.split(":", 1)[1]
        return f"https://job-boards.greenhouse.io/embed/job_app?for={token}&token={job.external_id}"
    if job.scope and job.scope.startswith("lever:") and not url.rstrip("/").endswith("/apply"):
        url = url.rstrip("/") + "/apply"
    if job.scope and job.scope.startswith("ashby:") and "/application" not in url:
        url = url.rstrip("/") + "/application"
    return url


def _interactive_captcha(page) -> bool:
    """A visible puzzle/checkbox challenge. Invisible score-based badges are not a challenge to solve."""
    for f in page.frames:
        u = f.url.lower()
        if ("recaptcha" in u and "anchor" in u and "size=invisible" not in u) or \
                ("hcaptcha" in u and "checkbox" in u) or "challenges.cloudflare.com" in u:
            return True
    return False


def app_svc_profile(app: Application) -> CandidateProfile | None:
    from sqlalchemy.orm import object_session
    db = object_session(app)
    return db.get(CandidateProfile, app.profile_id) if db else None


def run_one(page, app: Application, dry_run: bool) -> dict:
    """Fill (and if not dry-run, submit) one application. Returns an outcome dict."""
    job = app.job
    docs = {d.kind: d.content for d in app.documents}
    pdf = Path(tempfile.mkdtemp()) / "resume.pdf"
    pdf.write_bytes(render_pdf(docs.get("resume", "")))
    page.goto(_apply_url(job), wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    if _interactive_captcha(page):
        return {"result": "manual", "reason": "CAPTCHA challenge on form (never bypassed)"}
    profile = app.job and app_svc_profile(app)
    rules = answers_for(job, docs.get("cover_letter", ""), (profile.skills if profile else []))
    filled, missing = fill_page(page, rules, str(pdf))
    SHOTS.mkdir(parents=True, exist_ok=True)
    shot = SHOTS / f"app-{app.id}.png"
    page.screenshot(path=str(shot), full_page=True)
    if "resume" not in filled:
        missing.append("resume upload")
    if missing:
        return {"result": "manual", "reason": "unanswered required: " + "; ".join(missing)[:400],
                "filled": len(filled), "screenshot": str(shot)}
    if dry_run:
        return {"result": "dry_run_ok", "filled": len(filled), "screenshot": str(shot)}
    for sel in SUBMIT_SELECTORS:
        btn = page.locator(sel).first
        if btn.count():
            btn.click(timeout=5000)
            break
    else:
        return {"result": "manual", "reason": "submit button not found", "screenshot": str(shot)}
    try:
        page.wait_for_function("t => new RegExp(t, 'i').test(document.body.innerText)", arg=CONFIRM.pattern,
                               timeout=20000)
    except Exception:  # noqa: BLE001
        page.screenshot(path=str(shot), full_page=True)
        if re.search(r"confirm|thank|success", page.url, re.I):
            return {"result": "submitted", "ref": f"auto:{page.url[:200]}", "screenshot": str(shot)}
        return {"result": "check", "reason": "clicked submit but no confirmation seen", "screenshot": str(shot)}
    page.screenshot(path=str(shot), full_page=True)
    text = CONFIRM.search(page.inner_text("body"))
    return {"result": "submitted", "ref": f"auto:{(text.group(0) if text else 'confirmed')}@{page.url[:150]}",
            "screenshot": str(shot)}


def run_auto_apply(db: Session, force_dry_run: bool | None = None) -> dict:
    s = get_settings()
    dry = s.auto_apply_dry_run if force_dry_run is None else force_dry_run
    if not s.auto_apply_enabled and force_dry_run is None:
        return {"skipped": "AUTO_APPLY_ENABLED is false"}
    if is_paused(db):
        return {"skipped": "paused from dashboard"}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"skipped": "Playwright not installed: pip install -r requirements-autofill.txt "
                           "&& playwright install chromium"}
    summary = {"dry_run": dry, "submitted": 0, "dry_run_ok": 0, "manual": 0, "check": 0, "errors": 0, "items": []}
    for profile in db.scalars(select(CandidateProfile)):
        budget = s.auto_apply_daily_cap - used_today(db, profile.id)
        jobs = candidates(db, profile, max(0, budget))
        if not jobs:
            continue
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=s.auto_apply_headless)
            for job in jobs:
                try:
                    app = app_svc.prepare_application(db, profile, job.id)
                except app_svc.ApplicationBlocked as e:
                    summary["items"].append({"job": job.title, "company": job.company_name, "result": "skipped",
                                             "reason": str(e)})
                    continue
                app.apply_method = "auto"
                app.status, app.approved_at = "approved", utcnow()
                app.notes = "Auto-approved by your auto-apply rule."
                db.commit()
                page = browser.new_page()
                try:
                    out = run_one(page, app, dry)
                except Exception as e:  # noqa: BLE001 - one bad form never stops the batch
                    out = {"result": "manual", "reason": f"error: {type(e).__name__}"}
                    summary["errors"] += 1
                finally:
                    page.close()
                res = out["result"]
                if res == "submitted":
                    app_svc.mark_submitted(db, app, out["ref"], "portal")
                else:
                    if res == "dry_run_ok":
                        app.status, app.approved_at = "prepared", None
                    reason, shot = out.get("reason", "form filled OK"), out.get("screenshot", "-")
                    app.notes += f"\n[{res}] {reason} · screenshot: {shot}"
                    db.commit()
                summary[res if res in summary else "manual"] += 1
                summary["items"].append({"app_id": app.id, "job": job.title, "company": job.company_name, **out})
            browser.close()
    if summary["items"]:
        lines = [f"- [{i['result']}] {i['job']} @ {i['company']} {('— ' + i['reason']) if i.get('reason') else ''}"
                 for i in summary["items"]]
        mode = "TEST MODE (nothing submitted)" if dry else "LIVE"
        notify(db, kind="auto_apply", title=f"Hirenza auto-apply {mode}: {summary['submitted']} submitted, "
               f"{summary['manual'] + summary['check']} need you", text="\n".join(lines),
               dedupe_key=f"autoapply:{utcnow():%Y%m%d%H%M}")
    return summary
