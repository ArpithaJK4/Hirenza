from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """All configuration comes from the environment / .env. Nothing secret is hardcoded."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: str = "development"
    secret_key: SecretStr
    database_url: str = "postgresql+psycopg://hirenza:hirenza@localhost:5432/hirenza"
    redis_url: str = "redis://localhost:6379/0"
    access_token_expire_minutes: int = 720
    allow_registration: bool = True  # only the first user can register unless enabled
    cors_origins: CsvList = ["http://localhost:5173"]
    log_level: str = "INFO"

    # Confidentiality guardrails (hard blocks)
    current_employer_names: CsvList = []
    current_employer_domains: CsvList = []

    # Discovery
    http_timeout_seconds: float = 20.0
    http_user_agent: str = "HirenzaJobHunter/0.1 (personal job search; respects robots and rate limits)"
    company_seed_file: str = str(BASE_DIR / "data" / "companies.yaml")
    profile_seed_file: str = str(BASE_DIR / "data" / "profile.yaml")
    ats_concurrency: int = 8
    adzuna_app_id: str | None = None
    adzuna_app_key: SecretStr | None = None
    adzuna_countries: CsvList = ["in", "gb", "us", "de", "nl", "sg", "ca"]
    jsearch_api_key: SecretStr | None = None
    gmail_imap_user: str | None = None
    gmail_imap_app_password: SecretStr | None = None
    gmail_alert_lookback_days: int = 7

    # Notifications
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    notify_email_to: str | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    max_alerts_per_run: int = 15

    # LLM (optional — everything works rule/template-based without it)
    llm_provider: str = "none"  # anthropic | ollama | none
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    llm_daily_call_limit: int = 150
    llm_rerank_top_n: int = 20

    # Candidate contact details for autofill/cover letters — env only, never committed
    candidate_full_name: str | None = None
    candidate_email: str | None = None
    candidate_phone: str | None = None
    candidate_linkedin_url: str | None = None
    candidate_github_url: str | None = None
    candidate_location: str = "Bengaluru, India"

    # Auto-apply (public company ATS forms only: Greenhouse / Lever / Ashby). Off by default.
    auto_apply_enabled: bool = False
    auto_apply_dry_run: bool = True  # fill + screenshot, never click submit
    auto_apply_min_score: float = 80
    auto_apply_daily_cap: int = 10
    auto_apply_countries: CsvList = ["India", "Worldwide"]
    auto_apply_headless: bool = True
    candidate_current_company: str | None = None
    candidate_years_experience: str = "2"
    candidate_notice_period: str | None = None
    candidate_current_ctc: str | None = None
    candidate_expected_ctc: str | None = None
    candidate_willing_to_relocate: str | None = None  # yes | no
    candidate_needs_sponsorship_abroad: str = "yes"
    candidate_degree: str = "Master's"
    candidate_past_employers: CsvList = []  # e.g. "5Sec CyberPWN,Holla's Innovation,JSpiders"

    # Applications / outreach
    follow_up_days: int = 5
    max_upload_mb: int = 2
    signal_feeds: CsvList = [
        "https://inc42.com/buzz/feed/",
        "https://yourstory.com/feed",
        "https://techcrunch.com/category/venture/feed/",
        "https://economictimes.indiatimes.com/tech/funding/rssfeeds/78570540.cms",
    ]

    @field_validator("cors_origins", "current_employer_names", "current_employer_domains",
                     "adzuna_countries", "signal_feeds",
                     "auto_apply_countries", "candidate_past_employers", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
