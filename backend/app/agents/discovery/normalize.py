import hashlib
import html
import re
from datetime import UTC, datetime

from app.guardrails import normalize_company

INDIA_CITIES = {
    "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "hyderabad": "Hyderabad", "pune": "Pune",
    "chennai": "Chennai", "mumbai": "Mumbai", "navi mumbai": "Mumbai", "delhi": "Delhi NCR",
    "new delhi": "Delhi NCR", "gurgaon": "Delhi NCR", "gurugram": "Delhi NCR", "noida": "Delhi NCR",
    "ncr": "Delhi NCR", "kolkata": "Kolkata", "ahmedabad": "Ahmedabad", "kochi": "Kochi",
    "coimbatore": "Coimbatore", "jaipur": "Jaipur", "mysore": "Mysuru", "mysuru": "Mysuru",
    "trivandrum": "Thiruvananthapuram", "indore": "Indore", "chandigarh": "Chandigarh",
}

COUNTRY_PATTERNS = [
    ("India", r"\bindia\b|\bIN\b"),
    ("USA", r"\busa\b|united states|\bus\b|\bu\.s\.|new york|san francisco|seattle|austin|boston|"
            r"chicago|\b(ca|ny|wa|tx|ma)\b,?\s*(usa)?$"),
    ("UK", r"\buk\b|united kingdom|london|manchester|edinburgh|england"),
    ("Germany", r"germany|berlin|munich|münchen|hamburg|frankfurt"),
    ("Netherlands", r"netherlands|amsterdam|rotterdam|utrecht"),
    ("Singapore", r"singapore"),
    ("UAE", r"\buae\b|united arab emirates|dubai|abu dhabi"),
    ("Canada", r"canada|toronto|vancouver|montreal"),
    ("Ireland", r"ireland|dublin"),
    ("Australia", r"australia|sydney|melbourne"),
]
_COUNTRY_RX = [(c, re.compile(p, re.I)) for c, p in COUNTRY_PATTERNS]


_BLOCK = re.compile(r"<\s*(?:br|/p|/div|/li|/h[1-6]|/tr|li)\b[^>]*>", re.I)
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(raw: str | None) -> str:
    """Fast HTML -> text (~20x quicker than BeautifulSoup; plenty for skill/keyword matching)."""
    if not raw:
        return ""
    text = html.unescape(raw)
    if "<" in text:
        text = _SCRIPT.sub(" ", text)
        text = _BLOCK.sub("\n", text)
        text = html.unescape(_TAG.sub(" ", text))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_location(location: str | None) -> tuple[str | None, str | None]:
    """Return (country, city). City only resolved for India (priority market)."""
    loc = (location or "").lower()
    city = None
    for key in sorted(INDIA_CITIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", loc):
            city = INDIA_CITIES[key]
            break
    if city:
        return "India", city
    for country, rx in _COUNTRY_RX:
        if rx.search(location or ""):
            return country, None
    if re.search(r"worldwide|anywhere|global", loc):
        return "Worldwide", None
    return None, None


def detect_remote_type(location: str | None, title: str | None = None, description: str | None = None,
                       hint: str | None = None) -> str:
    if hint:
        h = hint.lower()
        if "hybrid" in h:
            return "hybrid"
        if "remote" in h:
            return "remote"
        if "onsite" in h or "on-site" in h or "in office" in h or "in-office" in h:
            return "onsite"
    head = f"{location or ''} {title or ''}".lower()
    if "hybrid" in head:
        return "hybrid"
    if "remote" in head or "work from home" in head or "wfh" in head:
        return "remote"
    desc = (description or "")[:3000].lower()
    if re.search(r"\bhybrid\b", desc):
        return "hybrid"
    if re.search(r"fully remote|100% remote|remote[- ]first|work from anywhere", desc):
        return "remote"
    if location:
        return "onsite"
    return "unknown"


_EXP_RANGE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*(?:\+|plus)?\s*(?:-|–|—|to)\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years|yrs|year)", re.I)
_EXP_MIN = re.compile(
    r"(?:minimum|min\.?|at least|over)?\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years|yrs|year)(?:'s|s)?"
    r"(?:\s+of)?(?:\s+[\w-]+){0,4}\s+(?:experience|exp)", re.I)


def extract_experience(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    m = _EXP_RANGE.search(text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo <= hi <= 30:
            return lo, hi
    mins = [float(x) for x in _EXP_MIN.findall(text) if float(x) <= 25]
    if mins:
        return min(mins), None
    return None, None


_LPA = re.compile(
    r"(?:₹|inr|rs\.?)?\s*(\d{1,3}(?:\.\d+)?)\s*(?:-|–|to)\s*(\d{1,3}(?:\.\d+)?)\s*"
    r"(?:lpa|lakhs?(?:\s*per\s*annum)?|l\.p\.a)", re.I)


def extract_salary_inr_lpa(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    m = _LPA.search(text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if 0 < lo <= hi <= 300:
            return lo, hi
    return None, None


def to_lpa(amount: float | None, currency: str | None, period: str | None = "year") -> float | None:
    """Normalise an INR amount to lakhs per annum."""
    if amount is None or (currency or "").upper() != "INR":
        return None
    yearly = amount * {"month": 12, "hour": 2000, "day": 250}.get(period or "year", 1)
    return round(yearly / 100_000, 2) if yearly > 1000 else yearly


_TITLE_NOISE = re.compile(r"\(.*?\)|\[.*?\]|[^a-z0-9 ]+")


def fingerprint(company: str, title: str, location: str | None = "") -> str:
    """Cross-source identity: company + title. Location is ignored because sources describe the same
    posting differently ("India" vs "Worldwide" vs "Remote"). Only compared ACROSS sources, so
    multi-city postings on one board are kept separately."""
    t = re.sub(r"\s+", " ", _TITLE_NOISE.sub(" ", title.lower())).strip()
    key = f"{normalize_company(company)}|{t}"
    return hashlib.sha256(key.encode()).hexdigest()


def parse_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, int | float):
            ts = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(ts, tz=UTC)
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None
