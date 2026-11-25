"""Applications, outreach, tracking: approval flow, duplicate blocks, guardrails, analytics."""
from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.application.resume import parse_resume, render_pdf, split_sections, tailor
from app.agents.discovery.service import ensure_sources, ingest_batch
from app.agents.discovery.sources.base import Batch
from app.agents.matching.service import run_matching
from app.models import AuditLog, JobListing
from tests.test_pipeline import raw

RESUME = b"""Jane Doe
DevOps Engineer | Bengaluru
PROFESSIONAL SUMMARY
DevOps engineer with Kubernetes, Terraform and AWS experience building CI/CD pipelines.
TECHNICAL SKILLS
Python, Django, Docker, Kubernetes, Helm, AWS, Terraform, GitHub Actions, Jenkins, SonarQube, Trivy, Linux
PROFESSIONAL EXPERIENCE
Acme Cyber Labs | DevOps Engineer | 2025 - Present
- Built Jenkins pipelines with SonarQube quality gates
- Provisioned AWS EKS clusters with Terraform modules
- Wrote internal Django admin tools
EDUCATION
MCA, 2025
"""


@pytest.fixture
def client(db):
    from app.core.ratelimit import limiter
    from app.main import app
    limiter.reset()
    return TestClient(app)


@pytest.fixture
def h(client):
    client.post("/api/auth/register", json={"email": "me@example.com", "password": "a-strong-password"})
    tok = client.post("/api/auth/login", data={"username": "me@example.com", "password": "a-strong-password"})
    return {"Authorization": f"Bearer {tok.json()['access_token']}"}


def seed_jobs(db):
    src = ensure_sources(db)["greenhouse"]
    ingest_batch(db, src, Batch([raw(1), raw(2, company="Acme Cyber Labs")]), {})
    ingest_batch(db, ensure_sources(db)["remoteok"], Batch([raw("r1")]), {})  # same role, other source
    db.commit()
    run_matching(db)
    good = db.scalar(select(JobListing).where(JobListing.external_id == "1"))
    bad = db.scalar(select(JobListing).where(JobListing.external_id == "2"))
    dup = db.scalar(select(JobListing).where(JobListing.external_id == "r1"))
    return good, bad, dup


def test_resume_parse_tailor_and_pdf():
    p = parse_resume(RESUME, "cv.txt")
    assert {"summary", "skills", "experience", "education"} <= set(p["sections"])
    md = tailor(p["sections"], p["skills"], ["Terraform", "AWS", "EKS", "ArgoCD"], "A")
    assert md.index("## Key Skills") < md.index("## Experience")
    assert "## Most Relevant Experience\n- Provisioned AWS EKS clusters" in md
    assert "ArgoCD" not in md  # never invents skills
    md_b = tailor(p["sections"], p["skills"], ["Terraform"], "B")
    assert md_b.index("## Experience") < md_b.index("## Key Skills")
    assert render_pdf(md).startswith(b"%PDF")
    assert split_sections("x")["header"] == "x"


def test_upload_rejects_fake_pdf(client, h):
    fake = {"file": ("cv.pdf", BytesIO(b"not a pdf" * 50), "application/pdf")}
    r = client.post("/api/resumes", headers=h, files=fake)
    assert r.status_code == 422


def test_application_flow_with_guardrails(client, h, db):
    good, bad, dup = seed_jobs(db)
    assert client.post(f"/api/jobs/{good.id}/prepare", headers=h).status_code == 409  # no resume yet
    client.post("/api/resumes", headers=h, files={"file": ("cv.txt", BytesIO(RESUME), "text/plain")})

    r = client.post(f"/api/jobs/{good.id}/prepare", headers=h)
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["status"] == "prepared" and {d["kind"] for d in app["documents"]} == {"resume", "cover_letter"}
    assert client.post(f"/api/jobs/{good.id}/prepare", headers=h).status_code == 409  # duplicate
    assert client.post(f"/api/jobs/{bad.id}/prepare", headers=h).status_code == 409  # current employer

    aid = app["id"]
    # cannot mark submitted or move stage before approval
    assert client.post(f"/api/applications/{aid}/submitted", headers=h,
                       json={"confirmation_ref": "x123"}).status_code == 409
    assert client.patch(f"/api/applications/{aid}/stage", headers=h, json={"stage": "screening"}).status_code == 422
    assert client.post(f"/api/applications/{aid}/approve", headers=h).json()["status"] == "approved"
    assert client.get(f"/api/applications/{aid}/resume.pdf", headers=h).content.startswith(b"%PDF")
    s = client.post(f"/api/applications/{aid}/submitted", headers=h, json={"confirmation_ref": "GH-confirm-42"})
    assert s.json()["stage"] == "applied" and s.json()["follow_up_at"]

    iv = client.post(f"/api/applications/{aid}/interviews", headers=h, json={"kind": "technical"}).json()
    assert "Likely questions" in iv["prep_pack"]
    assert client.put(f"/api/applications/{aid}/offer", headers=h, json={"ctc": 1400000}).json()["stage"] == "offer"
    a = client.get("/api/analytics", headers=h).json()
    assert a["totals"]["submitted"] == 1 and a["totals"]["interview_rate"] == 100.0
    assert a["by_resume_variant"][0]["key"] == "A"
    summary = client.get("/api/insights/summary", headers=h).json()
    assert summary["applications_submitted"] == 1 and summary["offers"] == 1
    assert dup.duplicate_of_id == good.id


def test_outreach_guardrails_and_approval(client, h, db):
    good, _, _ = seed_jobs(db)
    csv = ("Notes:\n\"export\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
           "Ravi,K,https://www.linkedin.com/in/ravi,,Good Co,SRE,01 Jan 2026\n"
           "Boss,X,https://www.linkedin.com/in/boss,,Acme Cyber Labs,CTO,01 Jan 2026\n")
    r = client.post("/api/outreach/import-linkedin-connections", headers=h,
                    files={"file": ("Connections.csv", BytesIO(csv.encode()), "text/csv")}).json()
    assert r == {"imported": 2, "excluded_current_employer": 1}
    refs = client.get("/api/outreach/referrals", headers=h).json()
    assert [x["name"] for x in refs] == ["Ravi K"] and refs[0]["jobs"][0]["job_id"] == good.id

    people = {p["name"]: p for p in client.get("/api/outreach/people", headers=h).json()}
    blocked = client.post("/api/outreach/messages", headers=h,
                          json={"recruiter_id": people["Boss X"]["id"], "channel": "email"})
    assert blocked.status_code == 409
    assert db.scalar(select(AuditLog).where(AuditLog.action == "guardrail.outreach_blocked"))

    note = client.post("/api/outreach/messages", headers=h, json={
        "recruiter_id": people["Ravi K"]["id"], "job_id": good.id, "channel": "linkedin_note"}).json()
    assert len(note["body"]) <= 300 and note["status"] == "draft"
    again = client.post("/api/outreach/messages", headers=h, json={
        "recruiter_id": people["Ravi K"]["id"], "job_id": good.id, "channel": "linkedin_note"})
    assert again.status_code == 409  # no duplicate messages
    mid = note["id"]
    assert client.post(f"/api/outreach/messages/{mid}/send", headers=h).status_code == 409  # not approved
    client.post(f"/api/outreach/messages/{mid}/approve", headers=h)
    assert client.post(f"/api/outreach/messages/{mid}/send", headers=h).status_code == 409  # LinkedIn: never automated
    assert client.post(f"/api/outreach/messages/{mid}/mark-sent", headers=h).json()["status"] == "sent"
    assert client.post(f"/api/outreach/messages/{mid}/mark-replied", headers=h).json()["status"] == "replied"

    p = client.post("/api/outreach/people", headers=h, json={
        "name": "Hira Recruiter", "company_name": "Good Co", "email": "hira@good.example"}).json()
    em = client.post("/api/outreach/messages", headers=h, json={"recruiter_id": p["id"], "channel": "email"}).json()
    client.post(f"/api/outreach/messages/{em['id']}/approve", headers=h)
    with patch("app.agents.outreach.service.send_email") as send:
        assert client.post(f"/api/outreach/messages/{em['id']}/send", headers=h).json()["status"] == "sent"
    assert send.call_args.kwargs["to"] == "hira@good.example"


def test_llm_cache_and_fallback(db, profile, monkeypatch):
    from app import llm
    assert not llm.available()
    with pytest.raises(llm.LLMUnavailable):
        llm.complete_json(db, purpose="x", system="s", prompt="p", schema={})
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    from app.core.config import get_settings
    get_settings.cache_clear()
    with patch("app.llm._anthropic_json", return_value=({"fit": 90}, 10, 5)) as call:
        a = llm.complete_json(db, purpose="rerank", system="s", prompt="p", schema={})
        b = llm.complete_json(db, purpose="rerank", system="s", prompt="p", schema={})
    assert a == b == {"fit": 90} and call.call_count == 1  # second call served from cache


def test_optimiser_needs_data_and_prune(db, profile):
    from app.agents.tracking.service import optimise, prune
    assert optimise(db, profile.id)["updated"] is False
    assert prune(db) == {"deleted_closed": 0, "trimmed_low_score": 0}


def test_signal_parsing(db):
    from app.agents.outreach.service import refresh_signals
    rss = ("<rss><channel><item><title>Zerodha Raises $50 Mn In Series B</title><link>https://n/1</link></item>"
           "<item><title>Acme Cyber Labs raises Series A</title><link>https://n/2</link></item>"
           "<item><title>Budget 2026 explained</title><link>https://n/3</link></item></channel></rss>")
    import respx
    with respx.mock:
        respx.get(url__regex=r".*").respond(text=rss)
        out = refresh_signals(db)
    assert out["added"] == 1  # current employer skipped, non-funding skipped
