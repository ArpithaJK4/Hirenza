import os

os.environ.update({
    "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
    "DATABASE_URL": "sqlite://",
    "CURRENT_EMPLOYER_NAMES": "Acme Cyber Labs Pvt Ltd,AcmeCyber",
    "CURRENT_EMPLOYER_DOMAINS": "acmecyber.example",
    "ADZUNA_APP_ID": "", "ADZUNA_APP_KEY": "", "JSEARCH_API_KEY": "",
    "SMTP_HOST": "", "TELEGRAM_BOT_TOKEN": "", "GMAIL_IMAP_USER": "",
})

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402

Settings.model_config["env_file"] = None  # tests must never read the developer's real .env
from app.core.db import Base, SessionLocal, reset_engine  # noqa: E402


@pytest.fixture(autouse=True)
def _settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)
    reset_engine(engine)
    session = SessionLocal()
    yield session
    session.close()
    reset_engine(None)
    engine.dispose()


@pytest.fixture
def profile(db):
    from app.bootstrap import create_user
    user = create_user(db, "owner@example.com", "a-strong-password")
    db.commit()
    return user.profile
