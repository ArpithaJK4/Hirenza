from app.agents.discovery.normalize import (
    detect_remote_type,
    extract_experience,
    extract_salary_inr_lpa,
    fingerprint,
    html_to_text,
    parse_datetime,
    parse_location,
    to_lpa,
)
from app.agents.matching.skills import canonicalize, extract_skills


def test_experience_ranges():
    assert extract_experience("We need 2-4 years of experience in DevOps") == (2, 4)
    assert extract_experience("1 to 3 yrs") == (1, 3)
    assert extract_experience("Minimum 3+ years of hands-on experience") == (3, None)
    assert extract_experience("great team") == (None, None)


def test_salary_lpa():
    assert extract_salary_inr_lpa("CTC: ₹8 - 15 LPA") == (8, 15)
    assert extract_salary_inr_lpa("10 to 18 lakhs per annum") == (10, 18)
    assert to_lpa(1_200_000, "INR") == 12
    assert to_lpa(100_000, "INR", "month") == 12
    assert to_lpa(100_000, "USD") is None


def test_location_and_remote():
    assert parse_location("Bangalore, Karnataka, India") == ("India", "Bengaluru")
    assert parse_location("Gurugram") == ("India", "Delhi NCR")
    assert parse_location("London, UK") == ("UK", None)
    assert parse_location("Remote - Worldwide")[0] == "Worldwide"
    assert detect_remote_type("Remote, India") == "remote"
    assert detect_remote_type("Pune", description="This is a hybrid role") == "hybrid"
    assert detect_remote_type("Pune") == "onsite"
    assert detect_remote_type("", hint="Hybrid") == "hybrid"


def test_fingerprint_ignores_noise_and_suffixes():
    a = fingerprint("Razorpay Software Pvt Ltd", "DevOps Engineer (Platform)", "Bengaluru")
    b = fingerprint("Razorpay", "DevOps Engineer", "Bangalore, India")
    assert a == b


def test_html_and_dates():
    assert html_to_text("&lt;p&gt;Hello&lt;/p&gt;") == "Hello"
    assert parse_datetime(1700000000000).year == 2023
    assert parse_datetime("2026-11-17T10:00:00Z").tzinfo is not None
    assert parse_datetime("garbage") is None


def test_skill_extraction():
    s = extract_skills("Experience with K8s, Terraform, AWS EKS and GitHub Actions; Python/Django a plus. "
                       "JavaScript nice to have")
    for k in ("Kubernetes", "Terraform", "AWS", "EKS", "GitHub Actions", "Python", "Django", "JavaScript"):
        assert k in s
    assert "Java" not in s
    assert {"EC2", "S3", "CI/CD"} <= canonicalize(["AWS", "GitHub Actions"])
