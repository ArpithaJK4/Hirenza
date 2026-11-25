"""Reads LinkedIn / Naukri job-alert emails from YOUR inbox (IMAP, read-only).

This is how LinkedIn and Naukri jobs are discovered without scraping those sites.
Nothing is ever posted or sent to LinkedIn: this adapter only reads mail.
"""
import asyncio
import email
import imaplib
import re
from datetime import timedelta
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from app.agents.discovery.sources.base import Batch, FetchContext, RawJob, SourceAdapter
from app.core.config import get_settings
from app.core.timeutil import utcnow

PROVIDERS = {
    "linkedin": {
        "senders": ["jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com"],
        "link": re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)"),
        "canonical": "https://www.linkedin.com/jobs/view/{id}/",
    },
    "naukri": {
        "senders": ["naukrialerts@naukri.com", "info@naukri.com", "jobalerts@naukri.com"],
        "link": re.compile(r"naukri\.com/job-listings-[\w-]*?-(\d{9,})"),
        "canonical": None,
    },
}
_SKIP_TEXT = re.compile(r"^(view|apply|see|easy apply|save|unsubscribe|more)\b", re.I)


def parse_alert_html(html: str, provider: str) -> list[RawJob]:
    cfg = PROVIDERS[provider]
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, RawJob] = {}
    for a in soup.find_all("a", href=True):
        m = cfg["link"].search(a["href"])
        if not m:
            continue
        job_id = m.group(1)
        title = a.get_text(" ", strip=True)
        if not title or _SKIP_TEXT.match(title) or len(title) > 150:
            continue
        if job_id in seen:
            continue
        # Company / location usually follow the title inside the same card.
        card = a.find_parent(["td", "div", "table"]) or a.parent
        lines = [ln.strip(" ·•|") for ln in card.get_text("\n", strip=True).split("\n")]
        lines = [ln for ln in lines if ln and ln != title and not _SKIP_TEXT.match(ln)]
        company, location = "Unknown", ""
        if lines:
            first = lines[0]
            if "·" in first:
                company, _, location = (p.strip() for p in first.partition("·"))
            else:
                company = first
                location = lines[1] if len(lines) > 1 else ""
        url = cfg["canonical"].format(id=job_id) if cfg["canonical"] else a["href"].split("?")[0]
        seen[job_id] = RawJob(external_id=f"{provider}:{job_id}", title=title, company_name=company[:200],
                              url=url, location=location[:300], raw={"via": f"{provider} alert email"})
    return list(seen.values())


class EmailAlertsSource(SourceAdapter):
    key, name, kind = "email_alerts", "LinkedIn & Naukri alert emails", "email"
    min_interval_minutes = 30

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.gmail_imap_user and s.gmail_imap_app_password)

    def _read(self) -> list[Batch]:
        s = get_settings()
        since = (utcnow() - timedelta(days=s.gmail_alert_lookback_days)).strftime("%d-%b-%Y")
        batches: list[Batch] = []
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            imap.login(s.gmail_imap_user, s.gmail_imap_app_password.get_secret_value())
            imap.select("INBOX", readonly=True)  # never modifies mail
            for provider, cfg in PROVIDERS.items():
                jobs: list[RawJob] = []
                for sender in cfg["senders"]:
                    typ, data = imap.search(None, "FROM", f'"{sender}"', "SINCE", since)
                    if typ != "OK":
                        continue
                    for num in data[0].split()[-50:]:
                        typ, msg_data = imap.fetch(num, "(BODY.PEEK[])")
                        if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                            continue
                        msg = email.message_from_bytes(msg_data[0][1])
                        sent = None
                        try:
                            sent = parsedate_to_datetime(msg.get("Date"))
                        except (TypeError, ValueError):
                            pass
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                html = part.get_payload(decode=True).decode(
                                    part.get_content_charset() or "utf-8", "replace")
                                for job in parse_alert_html(html, provider):
                                    job.posted_at = sent
                                    jobs.append(job)
                batches.append(Batch(jobs))
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001, S110
                pass
        return batches

    async def fetch(self, client, ctx: FetchContext) -> list[Batch]:
        return await asyncio.to_thread(self._read)
