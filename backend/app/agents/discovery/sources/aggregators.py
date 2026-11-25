"""Official aggregator APIs: Adzuna (has India) and JSearch (Google-for-Jobs aggregate via RapidAPI)."""
from app.agents.discovery.normalize import html_to_text, parse_datetime
from app.agents.discovery.sources.base import Batch, FetchContext, RawJob, SourceAdapter
from app.core.config import get_settings

ADZUNA_CURRENCY = {"in": "INR", "gb": "GBP", "us": "USD", "de": "EUR", "nl": "EUR", "sg": "SGD",
                   "ca": "CAD", "au": "AUD"}


class AdzunaSource(SourceAdapter):
    key, name, kind = "adzuna", "Adzuna", "api"
    min_interval_minutes = 120  # free tier ~250 calls/day
    KEYWORDS = "devops python sre kubernetes terraform platform cloud backend devsecops"

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.adzuna_app_id and s.adzuna_app_key)

    async def fetch(self, client, ctx: FetchContext) -> list[Batch]:
        s = get_settings()
        batches = []
        for country in s.adzuna_countries:
            pages = 2 if country == "in" else 1  # India first
            jobs: list[RawJob] = []
            for page in range(1, pages + 1):
                params = {
                    "app_id": s.adzuna_app_id, "app_key": s.adzuna_app_key.get_secret_value(),
                    "what_or": self.KEYWORDS, "max_days_old": 7, "results_per_page": 50,
                    "sort_by": "date", "content-type": "application/json",
                }
                try:
                    r = await client.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}",
                                         params=params)
                    r.raise_for_status()
                except Exception as e:  # noqa: BLE001
                    batches.append(Batch([], error=f"adzuna {country}: {type(e).__name__}"))
                    break
                results = r.json().get("results", [])
                for j in results:
                    jobs.append(RawJob(
                        external_id=str(j["id"]),
                        title=html_to_text(j.get("title")),
                        company_name=(j.get("company") or {}).get("display_name", "Unknown"),
                        url=j.get("redirect_url", ""),
                        description=html_to_text(j.get("description")),
                        location=(j.get("location") or {}).get("display_name", ""),
                        posted_at=parse_datetime(j.get("created")),
                        salary_min=j.get("salary_min"), salary_max=j.get("salary_max"),
                        salary_currency=ADZUNA_CURRENCY.get(country), salary_period="year",
                        raw={"id": j["id"], "country": country,
                             "salary_is_predicted": j.get("salary_is_predicted")},
                    ))
                if len(results) < 50:
                    break
            batches.append(Batch(jobs))
        return batches


class JSearchSource(SourceAdapter):
    key, name, kind = "jsearch", "JSearch (Google Jobs)", "api"
    min_interval_minutes = 720  # free tier is ~200 req/month
    HOST = "jsearch.p.rapidapi.com"
    QUERIES = [("devops OR sre OR platform engineer in India", "in"),
               ("python backend developer in India", "in")]

    def is_configured(self) -> bool:
        return bool(get_settings().jsearch_api_key)

    async def fetch(self, client, ctx: FetchContext) -> list[Batch]:
        key = get_settings().jsearch_api_key.get_secret_value()
        headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": self.HOST}
        batches = []
        for query, country in self.QUERIES:
            r = await client.get(f"https://{self.HOST}/search", headers=headers, params={
                "query": query, "page": 1, "num_pages": 1, "date_posted": "3days", "country": country})
            if r.status_code >= 400:
                batches.append(Batch([], error=f"jsearch HTTP {r.status_code}"))
                continue
            jobs = []
            for j in r.json().get("data", []):
                loc = ", ".join(p for p in [j.get("job_city"), j.get("job_state"), j.get("job_country")] if p)
                jobs.append(RawJob(
                    external_id=j["job_id"],
                    title=j.get("job_title", ""),
                    company_name=j.get("employer_name") or "Unknown",
                    url=j.get("job_apply_link") or j.get("job_google_link", ""),
                    apply_url=j.get("job_apply_link"),
                    description=j.get("job_description", ""),
                    location=loc,
                    posted_at=parse_datetime(j.get("job_posted_at_datetime_utc")),
                    remote_hint="remote" if j.get("job_is_remote") else None,
                    salary_min=j.get("job_min_salary"), salary_max=j.get("job_max_salary"),
                    salary_currency=j.get("job_salary_currency"),
                    salary_period={"YEAR": "year", "MONTH": "month", "HOUR": "hour"}.get(
                        j.get("job_salary_period") or "", None),
                    raw={"publisher": j.get("job_publisher")},
                ))
            batches.append(Batch(jobs))
        return batches
