from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import select

from app.agents.discovery.service import ensure_sources, ingest_batch, seed_companies
from app.agents.discovery.sources.base import Batch, RawJob
from app.agents.matching.service import run_matching, skill_gaps
from app.core.timeutil import utcnow
from app.models import AuditLog, Company, JobListing, JobMatch, Notification
from app.notifications.alerts import send_job_alerts


def raw(i, title="DevOps Engineer", company="Good Co", loc="Bengaluru, India", desc=None):
    return RawJob(external_id=str(i), title=title, company_name=company, url=f"https://x/{i}", location=loc,
                  description=desc or "Kubernetes, Terraform, AWS, Docker, ArgoCD. 1-3 years experience. " * 5,
                  posted_at=utcnow() - timedelta(hours=2))


def test_ingest_dedupe_closure_and_exclusion(db, profile):
    srcs = ensure_sources(db)
    gh, ro = srcs["greenhouse"], srcs["remoteok"]
    s = ingest_batch(db, gh, Batch([raw(1), raw(2, "SRE"), raw(3, company="Acme Cyber Labs")],
                                   scope="greenhouse:good", authoritative=True), {})
    assert (s["new"], s["excluded"]) == (3, 1)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "guardrail.job_excluded"))

    # same job again -> update, not new; job 2 vanished -> closed
    s = ingest_batch(db, gh, Batch([raw(1), raw(3, company="Acme Cyber Labs")], scope="greenhouse:good",
                                   authoritative=True), {})
    assert (s["new"], s["updated"], s["closed"]) == (0, 2, 1)

    # same role from another source -> flagged duplicate
    s = ingest_batch(db, ro, Batch([raw("r1", loc="Bangalore")]), {})
    assert s["duplicates"] == 1

    stats = run_matching(db)
    assert stats["scored"] == 1  # excluded, closed and duplicate jobs are never scored
    m = db.scalar(select(JobMatch))
    assert m.score >= 75 and "ArgoCD" in m.missing_skills
    assert skill_gaps(db, profile.id)["missing"][0]["skill"] == "ArgoCD"


def test_alerts_sent_once_and_respect_threshold(db, profile, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    monkeypatch.setenv("NOTIFY_EMAIL_TO", "me@example.com")
    from app.core.config import get_settings
    get_settings.cache_clear()

    src = ensure_sources(db)["greenhouse"]
    ingest_batch(db, src, Batch([raw(1), raw(2, title="Senior Marketing Manager")]), {})
    run_matching(db)
    with patch("app.notifications.send_email") as send:
        assert send_job_alerts(db)["alerted"] == 1
        assert send_job_alerts(db)["alerted"] == 0
    assert send.call_count == 1
    subject, body = send.call_args.args[:2]
    assert "DevOps Engineer" in body and "Marketing" not in body
    assert db.scalar(select(Notification)).status == "sent"


def test_email_failure_does_not_crash(db, profile, monkeypatch):
    for k, v in {"SMTP_HOST": "h", "SMTP_USER": "u", "SMTP_PASSWORD": "p", "NOTIFY_EMAIL_TO": "t@x.io"}.items():
        monkeypatch.setenv(k, v)
    from app.core.config import get_settings
    get_settings.cache_clear()
    ingest_batch(db, ensure_sources(db)["greenhouse"], Batch([raw(1)]), {})
    run_matching(db)
    with patch("app.notifications.send_email", side_effect=OSError("smtp down")):
        send_job_alerts(db)
    assert db.scalar(select(Notification)).status == "failed"


def test_seed_companies_marks_employer_excluded(db, tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("greenhouse:\n  - {name: Stripe, token: stripe}\n  - {name: Acme Cyber Labs, token: acme}\n")
    assert seed_companies(db, str(f)) == 2
    assert db.scalar(select(Company).where(Company.ats_token == "acme")).is_excluded
    assert not db.scalar(select(Company).where(Company.ats_token == "stripe")).is_excluded


def test_full_pipeline_with_failing_source(db, profile):
    """One broken source must not stop the run."""
    from app.workers.pipeline import run_pipeline

    async def boom(self, client, ctx):
        raise RuntimeError("source down")

    async def ok(self, client, ctx):
        return [Batch([raw(9)])]

    with patch("app.agents.discovery.sources.feeds.RemoteOKSource.fetch", boom), \
         patch("app.agents.discovery.sources.feeds.WeWorkRemotelySource.fetch", ok):
        out = run_pipeline(db, force=True, only=["remoteok", "weworkremotely"])
    assert out["discovery"]["status"] == "partial"
    assert out["discovery"]["sources"]["weworkremotely"]["new"] == 1
    assert out["matching"]["scored"] == 1
    assert db.scalar(select(JobListing).where(JobListing.external_id == "9"))
