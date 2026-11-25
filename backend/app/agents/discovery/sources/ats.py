"""Public job-board APIs of Greenhouse, Lever and Ashby. These are published by the ATS vendors
for exactly this purpose (embedding/reading a company's open jobs)."""
import asyncio

import httpx

from app.agents.discovery.normalize import html_to_text, parse_datetime
from app.agents.discovery.sources.base import Batch, CompanyBoard, FetchContext, RawJob, SourceAdapter
from app.core.config import get_settings


class _BoardAdapter(SourceAdapter):
    kind = "ats"
    min_interval_minutes = 30

    def url(self, token: str) -> str:
        raise NotImplementedError

    def parse(self, board: CompanyBoard, data) -> list[RawJob]:
        raise NotImplementedError

    async def _one(self, client: httpx.AsyncClient, board: CompanyBoard, sem: asyncio.Semaphore) -> Batch:
        scope = f"{self.key}:{board.token}"
        async with sem:
            try:
                r = await client.get(self.url(board.token), timeout=60)  # big boards are slow
            except httpx.HTTPError as e:
                return Batch([], scope=scope, company_id=board.company_id, error=f"network: {e}")
        if r.status_code == 404:
            return Batch([], scope=scope, company_id=board.company_id, error="board not found", dead=True)
        if r.status_code >= 400:
            return Batch([], scope=scope, company_id=board.company_id, error=f"HTTP {r.status_code}")
        try:
            jobs = self.parse(board, r.json())
        except (ValueError, KeyError, TypeError) as e:
            return Batch([], scope=scope, company_id=board.company_id, error=f"parse: {e}")
        return Batch(jobs, scope=scope, company_id=board.company_id, authoritative=True)

    async def fetch(self, client, ctx: FetchContext) -> list[Batch]:
        sem = asyncio.Semaphore(get_settings().ats_concurrency)
        return list(await asyncio.gather(*(self._one(client, b, sem) for b in ctx.boards)))


class GreenhouseSource(_BoardAdapter):
    key, name = "greenhouse", "Greenhouse job boards"

    def url(self, token):
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

    def parse(self, board, data):
        out = []
        for j in data.get("jobs", []):
            out.append(RawJob(
                external_id=str(j["id"]),
                title=j.get("title", "").strip(),
                company_name=board.name,
                url=j.get("absolute_url", ""),
                description=html_to_text(j.get("content")),
                location=(j.get("location") or {}).get("name", ""),
                posted_at=parse_datetime(j.get("first_published") or j.get("updated_at")),
                raw={"id": j["id"], "updated_at": j.get("updated_at")},
            ))
        return out


class LeverSource(_BoardAdapter):
    key, name = "lever", "Lever job boards"

    def url(self, token):
        return f"https://api.lever.co/v0/postings/{token}?mode=json"

    def parse(self, board, data):
        out = []
        for j in data:
            cats = j.get("categories") or {}
            desc = j.get("descriptionPlain") or html_to_text(j.get("description"))
            lists = "\n".join(
                f"{li.get('text', '')}\n{html_to_text(li.get('content'))}" for li in j.get("lists") or [])
            sal = j.get("salaryRange") or {}
            out.append(RawJob(
                external_id=j["id"],
                title=j.get("text", "").strip(),
                company_name=board.name,
                url=j.get("hostedUrl", ""),
                apply_url=j.get("applyUrl"),
                description=f"{desc}\n\n{lists}".strip(),
                location=cats.get("location") or ", ".join(cats.get("allLocations") or []),
                posted_at=parse_datetime(j.get("createdAt")),
                remote_hint=j.get("workplaceType"),
                salary_min=sal.get("min"), salary_max=sal.get("max"),
                salary_currency=sal.get("currency"),
                salary_period={"per-year-salary": "year", "per-month-salary": "month",
                               "per-hour-wage": "hour"}.get(sal.get("interval", ""), None),
                tags=[t for t in [cats.get("team"), cats.get("commitment")] if t],
                raw={"id": j["id"]},
            ))
        return out


class AshbySource(_BoardAdapter):
    key, name = "ashby", "Ashby job boards"

    def url(self, token):
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"

    def parse(self, board, data):
        out = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            loc = j.get("location") or ""
            secondary = [s.get("location") for s in j.get("secondaryLocations") or [] if s.get("location")]
            out.append(RawJob(
                external_id=j["id"],
                title=j.get("title", "").strip(),
                company_name=board.name,
                url=j.get("jobUrl", ""),
                apply_url=j.get("applyUrl"),
                description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                location=", ".join([loc, *secondary]) if secondary else loc,
                posted_at=parse_datetime(j.get("publishedAt")),
                remote_hint=j.get("workplaceType") or ("remote" if j.get("isRemote") else None),
                tags=[t for t in [j.get("department"), j.get("employmentType")] if t],
                raw={"id": j["id"], "compensation": (j.get("compensation") or {}).get("compensationTierSummary")},
            ))
        return out
