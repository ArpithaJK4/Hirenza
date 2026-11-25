from types import SimpleNamespace

import pytest

from app.agents.application.forms import answer, answers_for, pick_option


@pytest.fixture
def rules(monkeypatch):
    for k, v in {"CANDIDATE_FULL_NAME": "Asha Rao", "CANDIDATE_EMAIL": "a@example.com", "CANDIDATE_NOTICE_PERIOD":
                 "30 days", "CANDIDATE_PAST_EMPLOYERS": "Good Co", "CANDIDATE_WILLING_TO_RELOCATE": "yes"}.items():
        monkeypatch.setenv(k, v)
    from app.core.config import get_settings
    get_settings.cache_clear()
    job = SimpleNamespace(country="India", remote_type="hybrid", company_name="Rubrik")
    return answers_for(job, "Dear team...", ["Python", "Kubernetes", "AWS"])


def test_answers_from_saved_profile(rules):
    assert answer("First Name*", rules) == "Asha"
    assert answer("Legal Name", rules) == "Asha Rao"
    assert answer("What is your notice period?", rules) == "30 days"
    assert answer("Are you legally authorized to work in this country?", rules) == "Yes"
    assert answer("Are you open to work from Noida?", rules) == "Yes"
    assert answer("Country*", rules) == "India"


def test_honest_resume_based_answers(rules):
    assert answer("Have you ever been employed by Rubrik?", rules) == "No"
    assert answer("Do you possess 6 months of experience in Python?", rules) == "Yes"
    assert answer("Do you possess 2 years of experience in Golang?", rules) == "No"
    assert answer("Do you possess 2 years of experience in distributed systems?", rules) is None  # -> manual


def test_unknown_questions_are_never_guessed(rules, monkeypatch):
    assert answer("What is your favourite data structure and why?", rules) is None
    assert answer("Expected salary", rules) is None  # not set -> manual review, not a guess


def test_option_picking():
    assert pick_option(["Select...", "Yes", "No"], "No") == "No"
    assert pick_option(["Male", "Female", "I don't wish to answer"], "__DECLINE__") == "I don't wish to answer"
    assert pick_option(["Acknowledge/Confirm"], "__CHECK__") == "Acknowledge/Confirm"
    assert pick_option(["India +91", "Iceland +354"], "India") == "India +91"


def test_auto_apply_off_by_default_and_pausable(db, profile):
    from app.agents.application.auto_apply import is_paused, run_auto_apply, set_paused
    assert run_auto_apply(db) == {"skipped": "AUTO_APPLY_ENABLED is false"}
    set_paused(db, True)
    assert is_paused(db)
    assert run_auto_apply(db, force_dry_run=True) == {"skipped": "paused from dashboard"}


def test_candidates_skip_employer_and_non_ats(db, profile, monkeypatch):
    from app.agents.application.auto_apply import candidates
    from app.agents.discovery.service import ensure_sources, ingest_batch
    from app.agents.discovery.sources.base import Batch
    from app.agents.matching.service import run_matching
    from tests.test_pipeline import raw
    monkeypatch.setenv("AUTO_APPLY_MIN_SCORE", "50")
    from app.core.config import get_settings
    get_settings.cache_clear()
    srcs = ensure_sources(db)
    ingest_batch(db, srcs["greenhouse"], Batch([raw(1), raw(2, company="Acme Cyber Labs")], scope="greenhouse:x"), {})
    ingest_batch(db, srcs["remoteok"], Batch([raw("r9", title="Platform Engineer")]), {})
    db.commit()
    run_matching(db)
    jobs = candidates(db, profile, 10)
    assert [j.external_id for j in jobs] == ["1"]  # employer blocked, non-ATS source excluded
