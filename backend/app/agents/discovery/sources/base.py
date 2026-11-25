from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.core.config import get_settings


@dataclass
class RawJob:
    external_id: str
    title: str
    company_name: str
    url: str
    description: str = ""
    location: str = ""
    apply_url: str | None = None
    posted_at: datetime | None = None
    remote_hint: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    tags: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class Batch:
    """A group of jobs. If `authoritative` is True the batch is the complete current set for
    `scope`, so active jobs in that scope that are missing can be marked closed."""
    jobs: list[RawJob]
    scope: str | None = None
    company_id: int | None = None
    authoritative: bool = False
    error: str | None = None
    dead: bool = False  # e.g. 404 board -> disable


@dataclass
class CompanyBoard:
    company_id: int
    name: str
    token: str


@dataclass
class FetchContext:
    queries: list[str]
    boards: list[CompanyBoard] = field(default_factory=list)


class SourceAdapter(ABC):
    key: str
    name: str
    kind: str  # ats | api | rss | email
    min_interval_minutes: int = 15

    def is_configured(self) -> bool:
        return True

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient, ctx: FetchContext) -> list[Batch]: ...


def make_client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(
        timeout=s.http_timeout_seconds,
        headers={"User-Agent": s.http_user_agent, "Accept": "application/json"},
        follow_redirects=True,
    )
