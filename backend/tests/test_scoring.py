from datetime import timedelta
from types import SimpleNamespace

from app.agents.matching.scorer import score_job, title_score
from app.core.timeutil import utcnow
from app.guardrails import is_current_employer, normalize_company, text_mentions_current_employer

PROFILE = SimpleNamespace(
    target_roles=["DevOps Engineer", "Python Developer", "Site Reliability Engineer", "Platform Engineer"],
    skills=["Python", "Django", "Docker", "Kubernetes", "AWS", "Terraform", "GitHub Actions", "Linux"],
    years_experience=2.0, priority_cities=["Bengaluru", "Pune"], target_countries=["India", "UK"],
    salary_min_lpa=8,
)


def job(**kw):
    base = dict(title="DevOps Engineer", company_name="Good Co", description="x" * 400,
                skills=["Kubernetes", "Terraform", "AWS", "Docker"], experience_min=1, experience_max=3,
                country="India", city="Bengaluru", remote_type="hybrid", location="Bengaluru",
                salary_min=None, salary_max=None, salary_currency=None, salary_period=None,
                posted_at=utcnow() - timedelta(hours=3), is_active=True, raw={})
    base.update(kw)
    return SimpleNamespace(**base)


def test_perfect_fit_scores_high():
    r = score_job(job(), PROFILE)
    assert r.score >= 85
    assert r.freshness_bucket == "24h"
    assert r.missing_skills == []
    assert "devops" in r.explanation


def test_seniority_and_off_target_penalised():
    assert score_job(job(title="Principal DevOps Architect", experience_min=10, experience_max=None),
                     PROFILE).score < 50
    assert score_job(job(title="Senior Sales Manager", skills=[]), PROFILE).score <= 30
    assert title_score("Associate DevOps Engineer", PROFILE.target_roles)[0] == 1.0


def test_missing_skills_reported():
    r = score_job(job(skills=["Kubernetes", "ArgoCD", "Go"]), PROFILE)
    assert set(r.missing_skills) == {"ArgoCD", "Go"}
    assert "gaps" in r.explanation


def test_scam_signals_cap_score():
    r = score_job(job(description="Great DevOps role. Pay a registration fee of Rs 2000. " + "x" * 300), PROFILE)
    assert r.is_suspicious and r.score <= 25


def test_old_job_flagged_as_ghost():
    r = score_job(job(posted_at=utcnow() - timedelta(days=90)), PROFILE)
    assert r.freshness_bucket == "older"
    assert any("ghost" in x for x in r.suspicious_reasons)


def test_low_salary_penalised():
    good = score_job(job(salary_min=1_000_000, salary_max=1_400_000, salary_currency="INR"), PROFILE).score
    low = score_job(job(salary_min=300_000, salary_max=400_000, salary_currency="INR"), PROFILE).score
    assert good > low


def test_guardrails_current_employer():
    assert normalize_company("Acme Cyber Labs Pvt. Ltd.") == "acme cyber"
    assert is_current_employer("ACME CYBER LABS")
    assert is_current_employer("AcmeCyber Technologies")
    assert is_current_employer(None, url_or_email="hr@acmecyber.example")
    assert is_current_employer(None, url_or_email="https://careers.acmecyber.example/jobs/1")
    assert not is_current_employer("Acme Foods")
    assert text_mentions_current_employer("Hiring DevOps for Acme Cyber Labs via consultancy")
