"""Idempotent setup: sources, companies, skills vocabulary, owner user + profile."""
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.discovery.service import ensure_sources, seed_companies
from app.agents.matching.skills import SKILLS
from app.core.config import get_settings
from app.core.security import hash_password
from app.models import CandidateProfile, Skill, User


def seed_skills(db: Session) -> None:
    have = set(db.scalars(select(Skill.name)))
    for name, (cat, aliases) in SKILLS.items():
        if name not in have:
            db.add(Skill(name=name, category=cat, aliases=aliases))


def load_profile_defaults() -> dict:
    with open(get_settings().profile_seed_file) as f:
        return yaml.safe_load(f) or {}


def ensure_profile(db: Session, user: User) -> CandidateProfile:
    if user.profile:
        return user.profile
    p = CandidateProfile(**load_profile_defaults())
    user.profile = p
    db.add(p)
    db.flush()
    return p


def create_user(db: Session, email: str, password: str, is_admin: bool = True) -> User:
    user = User(email=email.lower().strip(), hashed_password=hash_password(password), is_admin=is_admin)
    db.add(user)
    db.flush()
    ensure_profile(db, user)
    return user


def bootstrap(db: Session) -> dict:
    ensure_sources(db)
    added = seed_companies(db)
    seed_skills(db)
    profiles = 0
    for user in db.scalars(select(User)):
        ensure_profile(db, user)
        profiles += 1
    db.commit()
    return {"companies_added": added, "profiles": profiles}
