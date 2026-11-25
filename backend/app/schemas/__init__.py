from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105


class UserOut(ORM):
    id: int
    email: str
    is_admin: bool


class ProfileOut(ORM):
    headline: str
    years_experience: float
    skills: list[str]
    target_roles: list[str]
    priority_cities: list[str]
    target_countries: list[str]
    salary_min_lpa: float
    salary_max_lpa: float
    match_threshold: int
    alert_threshold: int


class ProfileUpdate(BaseModel):
    headline: str | None = Field(None, max_length=255)
    years_experience: float | None = Field(None, ge=0, le=50)
    skills: list[str] | None = Field(None, max_length=200)
    target_roles: list[str] | None = Field(None, max_length=50)
    priority_cities: list[str] | None = Field(None, max_length=50)
    target_countries: list[str] | None = Field(None, max_length=50)
    salary_min_lpa: float | None = Field(None, ge=0, le=500)
    salary_max_lpa: float | None = Field(None, ge=0, le=500)
    match_threshold: int | None = Field(None, ge=0, le=100)
    alert_threshold: int | None = Field(None, ge=0, le=100)


class MatchOut(ORM):
    score: float
    breakdown: dict
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: str
    freshness_bucket: str
    is_suspicious: bool
    suspicious_reasons: list[str]
    status: str


class JobOut(ORM):
    id: int
    title: str
    company_name: str
    location: str
    country: str | None
    city: str | None
    remote_type: str
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    experience_min: float | None
    experience_max: float | None
    skills: list[str]
    url: str
    apply_url: str | None
    posted_at: datetime | None
    discovered_at: datetime
    is_active: bool
    source: str
    match: MatchOut | None = None


class JobDetailOut(JobOut):
    description: str


class JobPage(BaseModel):
    total: int
    items: list[JobOut]


class MatchStatusIn(BaseModel):
    status: str = Field(pattern="^(new|shortlisted|dismissed)$")


class SourceOut(ORM):
    key: str
    name: str
    kind: str
    enabled: bool
    min_interval_minutes: int
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    consecutive_failures: int
    jobs_found_total: int


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    min_interval_minutes: int | None = Field(None, ge=5, le=10080)


class ExecutionOut(ORM):
    id: int
    agent: str
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict
    error: str | None


class ConfigIn(BaseModel):
    value: dict
