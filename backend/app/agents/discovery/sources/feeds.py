"""Remote OK (public API) and We Work Remotely (public RSS)."""
import calendar

import feedparser

from app.agents.discovery.normalize import html_to_text, parse_datetime
from app.agents.discovery.sources.base import Batch, FetchContext, RawJob, SourceAdapter


class RemoteOKSource(SourceAdapter):
    key, name, kind = "remoteok", "Remote OK", "api"
    min_interval_minutes = 60  # their API asks for light usage + attribution
    URL = "https://remoteok.com/api"
    TAGS = {"devops", "python", "backend", "sysadmin", "cloud", "aws", "kubernetes", "security", "sre", "django"}

    async def fetch(self, client, ctx: FetchContext) -> list[Batch]:
        r = await client.get(self.URL)
        r.raise_for_status()
        jobs = []
        for j in r.json():
            if not isinstance(j, dict) or "id" not in j or "position" not in j:
                continue  # first element is the legal notice
            tags = {t.lower() for t in j.get("tags") or []}
            if not tags & self.TAGS:
                continue
            jobs.append(RawJob(
                external_id=str(j["id"]),
                title=j.get("position", "").strip(),
                company_name=j.get("company", "").strip(),
                url=j.get("url", ""),
                apply_url=j.get("apply_url") or j.get("url"),
                description=html_to_text(j.get("description")),
                location=j.get("location") or "Worldwide",
                posted_at=parse_datetime(j.get("epoch") or j.get("date")),
                remote_hint="remote",
                salary_min=j.get("salary_min") or None, salary_max=j.get("salary_max") or None,
                salary_currency="USD" if j.get("salary_min") else None, salary_period="year",
                tags=sorted(tags),
                raw={"id": j["id"], "source": "Remote OK"},
            ))
        return [Batch(jobs)]


class WeWorkRemotelySource(SourceAdapter):
    key, name, kind = "weworkremotely", "We Work Remotely", "rss"
    min_interval_minutes = 30
    FEEDS = [
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    ]

    async def fetch(self, client, ctx: FetchContext) -> list[Batch]:
        batches = []
        for url in self.FEEDS:
            try:
                r = await client.get(url, headers={"Accept": "application/rss+xml, application/xml"})
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001 - one feed failing must not stop the other
                batches.append(Batch([], error=f"{url}: {e}"))
                continue
            feed = feedparser.parse(r.text)
            jobs = []
            for e in feed.entries:
                company, _, title = (e.get("title") or "").partition(":")
                if not title:
                    company, title = "", company
                jobs.append(RawJob(
                    external_id=e.get("id") or e.get("link"),
                    title=title.strip(),
                    company_name=company.strip() or "Unknown",
                    url=e.get("link", ""),
                    description=html_to_text(e.get("description") or e.get("summary")),
                    location=e.get("region") or "Worldwide",
                    posted_at=parse_datetime(calendar.timegm(e.published_parsed)
                                             if e.get("published_parsed") else None),
                    remote_hint="remote",
                ))
            batches.append(Batch(jobs))
        return batches
