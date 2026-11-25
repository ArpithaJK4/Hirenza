import pytest
from fastapi.testclient import TestClient

from app.agents.discovery.service import ensure_sources, ingest_batch
from app.agents.discovery.sources.base import Batch
from app.agents.matching.service import run_matching
from tests.test_pipeline import raw


@pytest.fixture
def client(db):
    from app.core.ratelimit import limiter
    from app.main import app
    limiter.reset()
    return TestClient(app)


def login(client, email="me@example.com", pw="a-strong-password"):
    r = client.post("/api/auth/register", json={"email": email, "password": pw})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_auth_flow(client):
    assert client.get("/api/jobs").status_code == 401
    h = login(client)
    assert client.get("/api/auth/me", headers=h).json()["is_admin"] is True
    bad = client.post("/api/auth/login", data={"username": "me@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    assert client.post("/api/auth/register", json={"email": "x@example.com", "password": "short"}).status_code == 422


def test_jobs_filters_and_status(client, db):
    h = login(client)
    src = ensure_sources(db)["greenhouse"]
    ingest_batch(db, src, Batch([raw(1), raw(2, title="Python Developer", loc="London, UK"),
                                 raw(3, company="Acme Cyber Labs")]), {})
    db.commit()
    run_matching(db)

    page = client.get("/api/jobs", headers=h).json()
    assert page["total"] == 2  # employer job never shown
    assert client.get("/api/jobs?country=UK", headers=h).json()["total"] == 1
    assert client.get("/api/jobs?city=Bengaluru&min_score=60", headers=h).json()["total"] == 1
    top = page["items"][0]
    assert top["match"]["score"] >= page["items"][1]["match"]["score"]

    r = client.patch(f"/api/jobs/{top['id']}/status", json={"status": "shortlisted"}, headers=h)
    assert r.json()["status"] == "shortlisted"
    assert client.patch(f"/api/jobs/{top['id']}/status", json={"status": "bogus"}, headers=h).status_code == 422
    assert "description" in client.get(f"/api/jobs/{top['id']}", headers=h).json()

    s = client.get("/api/insights/summary", headers=h).json()
    assert s["active_jobs"] == 2
    assert client.get("/api/insights/skill-gaps", headers=h).json()["jobs_analysed"] >= 1


def test_profile_and_weights(client):
    h = login(client)
    r = client.put("/api/profile", json={"alert_threshold": 80, "years_experience": 2.5}, headers=h)
    assert r.json()["alert_threshold"] == 80
    assert client.put("/api/profile", json={"alert_threshold": 500}, headers=h).status_code == 422
    r = client.put("/api/config/matching-weights", json={"value": {"skills": 0.4}}, headers=h)
    assert r.json()["skills"] == 0.4
    assert client.put("/api/config/matching-weights", json={"value": {"hack": 1}}, headers=h).status_code == 422
