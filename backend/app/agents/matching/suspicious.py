"""Ghost-job and scam heuristics. Strong signals mark a job suspicious; weak ones reduce its score."""
import re

from app.agents.discovery.normalize import to_lpa
from app.core.timeutil import hours_since

STRONG = [
    (re.compile(r"registration fee|security deposit|training fee|pay (?:a |the )?fee|refundable deposit|"
                r"pay for (?:your )?training", re.I), "asks candidates to pay a fee/deposit"),
    (re.compile(r"(?:whatsapp|telegram)\s*(?:only|me|us|at|on)?\s*[:\-]?\s*\+?\d[\d\s-]{8,}", re.I),
     "contact via WhatsApp/Telegram number"),
    (re.compile(r"earn (?:up to )?(?:₹|rs\.?|\$)\s?\d+.*(?:per day|daily|from home)|unlimited (?:income|earning)",
                re.I), "income-scheme language"),
    (re.compile(r"no interview|direct joining without interview|100% job guarantee|guaranteed placement",
                re.I), "job-guarantee / no-interview claims"),
]
_PERSONAL_EMAIL = re.compile(r"[\w.+-]+@(?:gmail|yahoo|hotmail|outlook|rediffmail)\.com", re.I)


def assess(job) -> tuple[list[str], list[str]]:
    """Return (strong_reasons, weak_reasons)."""
    text = f"{job.title}\n{job.description or ''}"
    strong = [msg for rx, msg in STRONG if rx.search(text)]
    weak: list[str] = []
    if _PERSONAL_EMAIL.search(job.description or ""):
        weak.append("recruiter uses a personal email address")
    if job.description and len(job.description) < 200 and job.raw.get("via") is None:
        weak.append("very short job description")
    if (job.company_name or "").strip().lower() in {"", "unknown", "confidential", "hidden", "n/a"}:
        weak.append("company name not disclosed")
    age = hours_since(job.posted_at)
    if age is not None and age > 24 * 60 and job.is_active:
        weak.append("open for 60+ days (possible ghost job)")
    hi = to_lpa(job.salary_max, job.salary_currency, job.salary_period or "year")
    if hi and hi > 80 and (job.experience_max or job.experience_min or 0) <= 3:
        strong.append("unrealistic salary for experience level")
    return strong, weak
