"""hirenza CLI:  python -m app.cli <command>

  bootstrap                      seed sources, company boards, skills, profiles
  create-user EMAIL              create the owner account (password from HIRENZA_PASSWORD or prompt)
  pipeline [--force] [--only a,b]  discover -> match -> alert   (what the scheduler runs)
  discover / match / alert       run one stage
  top [--limit N] [--min-score S] [--fresh]   print best jobs
  gaps                           skill-gap radar
  sources                        source health
  autofill APP_ID                open the approved application in a browser and fill it (you click submit)
  submitted APP_ID REF           record a real submission with its confirmation reference
  signals / optimise / prune     hiring-signal radar, learn from outcomes, storage housekeeping
  scheduler [--every 15]         laptop mode: run the pipeline every N minutes until Ctrl+C
"""
import argparse
import getpass
import json
import os
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.logging import setup_logging
from app.models import CandidateProfile, JobListing, JobMatch, JobSource


def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


def cmd_top(db, args):
    q = (select(JobMatch, JobListing).join(JobListing, JobListing.id == JobMatch.job_id)
         .where(JobMatch.score >= args.min_score, JobMatch.is_suspicious.is_(False),
                JobListing.is_active.is_(True), JobListing.is_excluded.is_(False),
                JobMatch.status != "dismissed"))
    if args.fresh:
        q = q.where(JobMatch.freshness_bucket == "24h")
    rows = db.execute(q.order_by(JobMatch.score.desc()).limit(args.limit)).all()
    for m, j in rows:
        print(f"{m.score:5.1f}  [{m.freshness_bucket:>7}]  {j.title[:55]:<55}  {j.company_name[:25]:<25}  "
              f"{(j.city or j.country or '-')[:14]:<14}  {j.source.key}")
        print(f"       {m.explanation}\n       {j.apply_url or j.url}")
    if not rows:
        print("No matching jobs yet. Run `python -m app.cli pipeline --force` first.")


def run_scheduler(every: int) -> None:
    """Runs on the laptop while it is awake. Each run is isolated: an error never stops the loop."""
    import time

    from app.workers.pipeline import run_pipeline
    print(f"Hirenza scheduler: pipeline every {every} min (Ctrl+C to stop)", flush=True)
    while True:
        started = time.monotonic()
        try:
            with session_scope() as db:
                out = run_pipeline(db, trigger="laptop")
            d, m, a = out["discovery"], out["matching"], out["alerts"]
            print(f"{time.strftime('%H:%M')} new={d.get('new_total', 0)} scored={m.get('scored', 0)} "
                  f"high={m.get('high', 0)} alerted={a.get('alerted', 0)}", flush=True)
        except Exception as e:  # noqa: BLE001 - keep the loop alive
            print(f"{time.strftime('%H:%M')} run failed: {e!r}", flush=True)
        time.sleep(max(60, every * 60 - (time.monotonic() - started)))


def main(argv=None):
    setup_logging(get_settings().log_level)
    p = argparse.ArgumentParser(prog="hirenza")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap")
    cu = sub.add_parser("create-user")
    cu.add_argument("email")
    for name in ("pipeline", "discover"):
        sp = sub.add_parser(name)
        sp.add_argument("--force", action="store_true", help="ignore per-source intervals")
        sp.add_argument("--only", default="", help="comma-separated source keys")
    sm = sub.add_parser("match")
    sm.add_argument("--rescore", action="store_true")
    sub.add_parser("alert")
    t = sub.add_parser("top")
    t.add_argument("--limit", type=int, default=20)
    t.add_argument("--min-score", type=float, default=55)
    t.add_argument("--fresh", action="store_true", help="only last 24h")
    sub.add_parser("gaps")
    sub.add_parser("sources")
    af = sub.add_parser("autofill")
    af.add_argument("app_id", type=int)
    sb = sub.add_parser("submitted")
    sb.add_argument("app_id", type=int)
    sb.add_argument("ref")
    aa = sub.add_parser("auto-apply")
    aa.add_argument("--live", action="store_true", help="really submit (default: test mode)")
    for name in ("signals", "optimise", "prune"):
        sub.add_parser(name)
    sc = sub.add_parser("scheduler")
    sc.add_argument("--every", type=int, default=15, help="minutes between runs")
    args = p.parse_args(argv)

    if args.cmd == "scheduler":
        return run_scheduler(args.every)

    with session_scope() as db:
        if args.cmd == "bootstrap":
            from app.bootstrap import bootstrap
            _print(bootstrap(db))
        elif args.cmd == "create-user":
            from app.bootstrap import create_user
            pw = os.environ.get("HIRENZA_PASSWORD") or getpass.getpass("Password (min 10 chars): ")
            if len(pw) < 10:
                sys.exit("Password must be at least 10 characters")
            u = create_user(db, args.email, pw)
            print(f"Created user {u.id} with profile")
        elif args.cmd == "pipeline":
            from app.workers.pipeline import run_pipeline
            only = [s for s in args.only.split(",") if s] or None
            _print(run_pipeline(db, trigger="cli", force=args.force, only=only))
        elif args.cmd == "discover":
            from app.agents.discovery.service import run_discovery
            only = [s for s in args.only.split(",") if s] or None
            _print(run_discovery(db, only=only, force=args.force))
        elif args.cmd == "match":
            from app.agents.matching.service import run_matching
            _print(run_matching(db, rescore=args.rescore))
        elif args.cmd == "alert":
            from app.notifications.alerts import send_job_alerts
            _print(send_job_alerts(db))
        elif args.cmd == "top":
            cmd_top(db, args)
        elif args.cmd == "gaps":
            from app.agents.matching.service import skill_gaps
            profile = db.scalar(select(CandidateProfile))
            if not profile:
                sys.exit("No profile. Run create-user first.")
            g = skill_gaps(db, profile.id)
            print(f"Analysed {g['jobs_analysed']} relevant jobs (last 14 days)\n\nMost-demanded skills you lack:")
            for r in g["missing"]:
                print(f"  {r['pct']:>3}%  {r['skill']}")
            print("\nYour strongest matching skills:")
            for r in g["strengths"]:
                print(f"  {r['pct']:>3}%  {r['skill']}")
        elif args.cmd == "autofill":
            from app.agents.application.autofill import run_autofill
            from app.models import Application
            a = db.get(Application, args.app_id)
            if not a:
                sys.exit("Application not found")
            run_autofill(a)
            print(f"If you submitted it: python -m app.cli submitted {a.id} '<confirmation ref>'")
        elif args.cmd == "submitted":
            from app.agents.application.service import ApplicationBlocked, mark_submitted
            from app.models import Application
            a = db.get(Application, args.app_id)
            try:
                mark_submitted(db, a, args.ref, "user_attested")
            except (ApplicationBlocked, AttributeError) as e:
                sys.exit(str(e) or "Application not found")
            print("Recorded. Follow-up reminder set.")
        elif args.cmd == "auto-apply":
            from app.agents.application.auto_apply import run_auto_apply
            _print(run_auto_apply(db, force_dry_run=not args.live))
        elif args.cmd == "signals":
            from app.agents.outreach.service import refresh_signals
            _print(refresh_signals(db))
        elif args.cmd == "optimise":
            from app.agents.tracking.service import optimise
            profile = db.scalar(select(CandidateProfile))
            _print(optimise(db, profile.id))
        elif args.cmd == "prune":
            from app.agents.tracking.service import prune
            _print(prune(db))
        elif args.cmd == "sources":
            for s in db.scalars(select(JobSource).order_by(JobSource.key)):
                print(f"{s.key:<16} {'on ' if s.enabled else 'off'} {s.last_status or '-':<8} "
                      f"every {s.min_interval_minutes:>4}m  total={s.jobs_found_total:<6} "
                      f"last={s.last_run_at}  {(s.last_error or '')[:80]}")
            n = db.scalar(select(JobListing.id).order_by(JobListing.id.desc()).limit(1))
            print(f"\nlatest job id: {n}")


if __name__ == "__main__":
    main()
