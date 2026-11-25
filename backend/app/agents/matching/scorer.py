"""Layer-1 rule-based scorer. Deterministic, fast and free (no LLM tokens).
LLM re-ranking (phase 2) only runs on jobs this scorer already ranks highly."""
import re
from dataclasses import dataclass, field

from app.agents.discovery.normalize import to_lpa
from app.agents.matching import suspicious
from app.agents.matching.skills import canonicalize
from app.core.timeutil import hours_since

DEFAULT_WEIGHTS = {"title": 0.27, "skills": 0.25, "experience": 0.15, "location": 0.17,
                   "freshness": 0.13, "salary": 0.03}
SKILL_PRIOR = 2  # jobs listing few skills give weak evidence: shrink toward 0.5

ROLE_FAMILIES: dict[str, list[str]] = {
    "devops": [r"devops", r"dev ops", r"build (?:and|&) release", r"release engineer", r"ci/?cd engineer"],
    "devsecops": [r"devsecops", r"cloud security", r"security engineer", r"application security"],
    "sre": [r"site reliability", r"\bsre\b", r"reliability engineer"],
    "platform": [r"platform engineer", r"infrastructure engineer", r"infra engineer", r"systems engineer"],
    "cloud": [r"cloud engineer", r"cloud ops", r"cloudops", r"aws engineer", r"cloud infrastructure",
              r"cloud developer"],
    "python": [r"python", r"django", r"fastapi"],
    "backend": [r"back-?end", r"api developer", r"server-side"],
}
_FAMILY_RX = {k: re.compile("|".join(v), re.I) for k, v in ROLE_FAMILIES.items()}
_WEAK_TECH = re.compile(r"software engineer|software developer|sde\b|developer|engineer", re.I)
_TOO_SENIOR = re.compile(r"\b(staff|principal|director|head of|vp\b|vice president|distinguished|architect)\b",
                         re.I)
_SENIOR = re.compile(r"\b(senior|sr\.?|lead|manager|iii|iv)\b", re.I)
_JUNIOR = re.compile(r"\b(junior|jr\.?|associate|entry|graduate|ii|level 2|l2)\b", re.I)
_INTERN = re.compile(r"\bintern(ship)?\b|\bco-?op\b|\btrainee\b|\bapprentice", re.I)
_OTHER_LANG = re.compile(r"\b(ruby|rails|php|\.net|c#|c\+\+|scala|rust|elixir|kotlin|swift|node(?:\.?js)?|golang)\b",
                         re.I)
_OFF_TARGET = re.compile(r"\b(sales|marketing|recruiter|account executive|designer|data scientist|"
                         r"android|ios|frontend|front-end|qa |tester|support engineer|intern\b)", re.I)

INTL_TARGETS = {"USA", "UK", "Germany", "Netherlands", "Singapore", "UAE", "Canada", "Worldwide"}


@dataclass
class ScoreResult:
    score: float
    breakdown: dict
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: str
    freshness_bucket: str
    is_suspicious: bool
    suspicious_reasons: list[str] = field(default_factory=list)


def title_score(title: str, target_roles: list[str]) -> tuple[float, str]:
    target_fams = {f for f, rx in _FAMILY_RX.items() for r in target_roles if rx.search(r)}
    job_fams = {f for f, rx in _FAMILY_RX.items() if rx.search(title)}
    if _OFF_TARGET.search(title) and not job_fams:
        return 0.0, "off-target role"
    if job_fams & target_fams:
        base, why = 1.0, f"{'/'.join(sorted(job_fams & target_fams))} role"
    elif _WEAK_TECH.search(title):
        base, why = 0.35, "generic engineering title"
    else:
        return 0.05, "title not in target roles"
    if _INTERN.search(title):
        return base * 0.3, why + " (internship)"
    if "backend" in job_fams and not job_fams & {"python", "devops", "sre", "platform", "cloud"} \
            and _OTHER_LANG.search(title):
        base, why = base * 0.5, why + " (non-Python stack)"
    if _TOO_SENIOR.search(title):
        return base * 0.15, why + " (too senior)"
    if _SENIOR.search(title):
        return base * 0.55, why + " (senior)"
    if _JUNIOR.search(title):
        return min(1.0, base * 1.0), why + " (junior/associate fit)"
    return base, why


def experience_score(exp_min: float | None, exp_max: float | None, years: float) -> float:
    if exp_min is None:
        return 0.7
    if exp_min <= years + 0.5 and (exp_max is None or exp_max >= years - 0.5):
        return 1.0
    if exp_min <= years + 1.5:
        return 0.6
    if exp_max is not None and exp_max < years - 2:
        return 0.6  # under-levelled, still possible
    return max(0.0, 1 - (exp_min - years) * 0.3)


def location_score(job, priority_cities: list[str], target_countries: list[str]) -> float:
    """India first. Abroad: remote-anywhere is good; country-locked remote usually needs local work
    authorisation; onsite abroad needs visa sponsorship (rare at ~2 yrs)."""
    if job.country == "India":
        if job.remote_type == "remote" or (job.city and job.city in priority_cities):
            return 1.0
        return 0.8
    if job.remote_type == "remote" and job.country in (None, "Worldwide"):
        return 0.85
    if job.country is None:
        return 0.5
    wanted = job.country in set(target_countries) | INTL_TARGETS
    if job.remote_type == "remote":
        return 0.45 if wanted else 0.3
    return 0.15 if wanted else 0.05


def freshness(job) -> tuple[float, str, float | None]:
    age = hours_since(job.posted_at)
    if age is None:
        return 0.5, "unknown", None
    if age <= 24:
        return 1.0, "24h", age
    if age <= 72:
        return 0.8, "7d", age
    if age <= 24 * 7:
        return 0.6, "7d", age
    if age <= 24 * 21:
        return 0.25, "older", age
    return 0.05, "older", age


def salary_score(job, min_lpa: float) -> float:
    if job.salary_min is None and job.salary_max is None:
        return 0.6
    hi = to_lpa(job.salary_max or job.salary_min, job.salary_currency, job.salary_period or "year")
    if hi is None:
        return 0.8  # foreign currency: usually above Indian targets
    return 1.0 if hi >= min_lpa else 0.25


def score_job(job, profile, weights: dict | None = None, boosts: dict | None = None) -> ScoreResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    t, t_why = title_score(job.title, profile.target_roles or [])

    have = canonicalize(profile.skills or [])
    jd = list(dict.fromkeys(job.skills or []))
    matched = [s for s in jd if s in have]
    missing = [s for s in jd if s not in have]
    sk = (len(matched) + 0.5 * SKILL_PRIOR) / (len(jd) + SKILL_PRIOR)
    sk = min(1.0, sk * 1.15)

    ex = experience_score(job.experience_min, job.experience_max, profile.years_experience or 0)
    lo = location_score(job, profile.priority_cities or [], profile.target_countries or [])
    fr, bucket, age = freshness(job)
    sa = salary_score(job, profile.salary_min_lpa or 0)

    parts = {"title": t, "skills": sk, "experience": ex, "location": lo, "freshness": fr, "salary": sa}
    total = sum(parts[k] * w[k] for k in parts) / sum(w.values()) * 100
    if t < 0.1:
        total = min(total, 30)  # wrong role family can never rank high
    if _TOO_SENIOR.search(job.title):
        total = min(total, 40)  # staff/principal/architect roles are out of reach at ~2 yrs
    if ex == 0.0:
        total = min(total, 45)  # asks for far more experience than the candidate has

    if boosts:  # learned from real outcomes by the optimisation agent
        src = getattr(getattr(job, "source", None), "key", None)
        fam = next((f for f, rx in _FAMILY_RX.items() if rx.search(job.title)), None)
        total += (boosts.get("source") or {}).get(src, 0) + (boosts.get("family") or {}).get(fam, 0)

    strong, weak = suspicious.assess(job)
    total -= 6 * len(weak)
    if strong:
        total = min(total, 25)
    total = round(max(0.0, min(100.0, total)), 1)

    bits = [t_why]
    if jd:
        bits.append(f"{len(matched)}/{len(jd)} skills match" + (f" ({', '.join(matched[:5])})" if matched else ""))
    if job.experience_min is not None:
        rng = f"{job.experience_min:g}-{job.experience_max:g}" if job.experience_max else f"{job.experience_min:g}+"
        bits.append(f"asks {rng} yrs ({'fits' if ex >= 0.9 else 'stretch' if ex >= 0.5 else 'mismatch'})")
    loc = job.city or job.country or job.location or "location unknown"
    bits.append(f"{loc}{' · ' + job.remote_type if job.remote_type != 'unknown' else ''}")
    if age is not None:
        bits.append(f"posted {int(age)}h ago" if age < 48 else f"posted {int(age // 24)}d ago")
    if missing:
        bits.append(f"gaps: {', '.join(missing[:5])}")

    return ScoreResult(
        score=total, breakdown={k: round(v, 3) for k, v in parts.items()},
        matched_skills=matched, missing_skills=missing, explanation="; ".join(bits),
        freshness_bucket=bucket, is_suspicious=bool(strong), suspicious_reasons=strong + weak,
    )
