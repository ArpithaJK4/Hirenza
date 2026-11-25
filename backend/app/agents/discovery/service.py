import asyncio
import hashlib
import logging
from datetime import timedelta

import yaml
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.discovery.normalize import (
    detect_remote_type,
    extract_experience,
    extract_salary_inr_lpa,
    fingerprint,
    parse_location,
)
from app.agents.discovery.sources import ADAPTERS
from app.agents.discovery.sources.base import (
    Batch,
    CompanyBoard,
    FetchContext,
    RawJob,
    SourceAdapter,
    make_client,
)
from app.agents.matching.skills import extract_skills
from app.core.config import get_settings
from app.core.timeutil import as_utc, utcnow
from app.guardrails import is_current_employer, normalize_company, text_mentions_current_employer
from app.models import AuditLog, CandidateProfile, Company, JobListing, JobSource

log = logging.getLogger(__name__)


def ensure_sources(db: Session) -> dict[str, JobSource]:
    existing = {s.key: s for s in db.scalars(select(JobSource))}
    for key, cls in ADAPTERS.items():
        if key not in existing:
            src = JobSource(key=key, name=cls.name, kind=cls.kind, min_interval_minutes=cls.min_interval_minutes)
            db.add(src)
            existing[key] = src
    db.flush()
    return existing


def seed_companies(db: Session, path: str | None = None) -> int:
    path = path or get_settings().company_seed_file
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    added = 0
    for ats_type in ("greenhouse", "lever", "ashby"):
        for entry in data.get(ats_type, []) or []:
            name, token = entry["name"], entry["token"]
            norm = normalize_company(name)
            company = db.scalar(select(Company).where(Company.normalized_name == norm))
            if company is None:
                company = Company(name=name, normalized_name=norm)
                db.add(company)
                added += 1
            company.ats_type, company.ats_token = ats_type, token
            company.country = entry.get("country")
            company.is_excluded = is_current_employer(name)
    db.flush()
    return added


def _get_or_create_company(db: Session, name: str, cache: dict[str, Company]) -> Company | None:
    norm = normalize_company(name)
    if not norm or norm == "unknown":
        return None
    if norm in cache:
        return cache[norm]
    company = db.scalar(select(Company).where(Company.normalized_name == norm))
    if company is None:
        company = Company(name=name[:200], normalized_name=norm[:200], is_excluded=is_current_employer(name))
        db.add(company)
        db.flush()
    cache[norm] = company
    return company


def _build_context(db: Session, adapter: SourceAdapter) -> FetchContext:
    roles = set()
    for p in db.scalars(select(CandidateProfile)):
        roles.update(p.target_roles or [])
    boards = []
    if adapter.kind == "ats":
        q = select(Company).where(Company.ats_type == adapter.key, Company.board_enabled.is_(True),
                                  Company.is_excluded.is_(False))
        boards = [CompanyBoard(c.id, c.name, c.ats_token) for c in db.scalars(q) if c.ats_token]
    return FetchContext(queries=sorted(roles), boards=boards)


def _is_due(src: JobSource, force: bool) -> bool:
    if force or src.last_run_at is None:
        return True
    return utcnow() - as_utc(src.last_run_at) >= timedelta(minutes=src.min_interval_minutes - 1)


def _apply_fields(job: JobListing, raw: RawJob) -> None:
    text = f"{raw.title}\n{raw.description}"
    country, city = parse_location(raw.location)
    exp_min, exp_max = extract_experience(raw.description)
    sal_min, sal_max, cur, period = raw.salary_min, raw.salary_max, raw.salary_currency, raw.salary_period
    if sal_min is None and sal_max is None:
        lo, hi = extract_salary_inr_lpa(raw.description)
        if lo is not None:
            sal_min, sal_max, cur, period = lo * 100_000, hi * 100_000, "INR", "year"
    job.title = raw.title[:300]
    job.company_name = raw.company_name[:200]
    job.location = (raw.location or "")[:300]
    job.country, job.city = country, city
    job.remote_type = detect_remote_type(raw.location, raw.title, raw.description, raw.remote_hint)
    if job.remote_type == "remote" and country is None:
        job.country = "Worldwide"
    job.salary_min, job.salary_max, job.salary_currency, job.salary_period = sal_min, sal_max, cur, period
    job.experience_min, job.experience_max = exp_min, exp_max
    job.skills = extract_skills(text)
    job.description = raw.description or ""
    job.url = raw.url[:1000]
    job.apply_url = (raw.apply_url or raw.url)[:1000]
    if raw.posted_at:
        job.posted_at = raw.posted_at
    job.raw = raw.raw or {}


def _content_hash(raw: RawJob) -> str:
    key = f"{raw.title}|{raw.company_name}|{raw.location}|{raw.salary_min}|{raw.salary_max}|{raw.description}"
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()


def _chunks(items: list, n: int = 500):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def ingest_batch(db: Session, src: JobSource, batch: Batch, company_cache: dict) -> dict:
    """Upsert a batch with O(1) round-trips per 500 jobs (matters on remote DBs like Neon)."""
    stats = {"new": 0, "updated": 0, "closed": 0, "excluded": 0, "duplicates": 0}
    now = utcnow()
    raws: dict[str, RawJob] = {}
    for raw in batch.jobs:
        if raw.external_id and raw.title and raw.url:
            raws[str(raw.external_id)[:255]] = raw
    ids = list(raws)

    existing: dict[str, JobListing] = {}
    for chunk in _chunks(ids):
        for job in db.scalars(select(JobListing).where(JobListing.source_id == src.id,
                                                       JobListing.external_id.in_(chunk))):
            existing[job.external_id] = job

    unchanged: list[int] = []
    new_jobs: list[JobListing] = []
    for ext, raw in raws.items():
        job = existing.get(ext)
        h = _content_hash(raw)
        if job is not None and (job.raw or {}).get("_h") == h and job.is_active:
            unchanged.append(job.id)
            stats["updated"] += 1
            continue
        is_new = job is None
        if is_new:
            job = JobListing(source_id=src.id, external_id=ext, scope=batch.scope, discovered_at=now)
        _apply_fields(job, raw)
        job.raw = {**(raw.raw or {}), "_h": h}
        job.last_seen_at, job.is_active, job.closed_at = now, True, None
        if is_new and job.posted_at is None:
            job.posted_at = now if src.kind in ("rss", "email") else None
        company = (db.get(Company, batch.company_id) if batch.company_id
                   else _get_or_create_company(db, raw.company_name, company_cache))
        job.company_id = company.id if company else None

        excluded = (bool(company and company.is_excluded)
                    or is_current_employer(raw.company_name, url_or_email=raw.url)
                    or text_mentions_current_employer(f"{raw.company_name} {raw.title}"))
        if excluded and not job.is_excluded:
            stats["excluded"] += 1
            db.add(AuditLog(action="guardrail.job_excluded", entity="job_listing",
                            details={"company": raw.company_name, "title": raw.title, "source": src.key}))
        job.is_excluded = excluded
        if is_new:
            job.fingerprint = fingerprint(raw.company_name, raw.title, raw.location)
            new_jobs.append(job)
            db.add(job)
            stats["new"] += 1
        else:
            stats["updated"] += 1

    # Cross-source duplicates: one query for all new fingerprints
    fps = list({j.fingerprint for j in new_jobs})
    originals: dict[str, int] = {}
    for chunk in _chunks(fps):
        for fp, jid in db.execute(
                select(JobListing.fingerprint, JobListing.id).where(
                    JobListing.fingerprint.in_(chunk), JobListing.source_id != src.id,
                    JobListing.duplicate_of_id.is_(None), JobListing.is_active.is_(True))):
            originals.setdefault(fp, jid)
    for job in new_jobs:
        if job.fingerprint in originals:
            job.duplicate_of_id = originals[job.fingerprint]
            stats["duplicates"] += 1

    for chunk in _chunks(unchanged):
        db.execute(update(JobListing).where(JobListing.id.in_(chunk)).values(last_seen_at=now))
    db.flush()

    if batch.authoritative and batch.scope and not batch.error:
        q = (update(JobListing)
             .where(JobListing.source_id == src.id, JobListing.scope == batch.scope,
                    JobListing.is_active.is_(True))
             .values(is_active=False, closed_at=now))
        if ids:
            q = q.where(JobListing.external_id.not_in(ids))
        stats["closed"] = db.execute(q).rowcount or 0
    return stats


async def _fetch_all(pairs: list[tuple[SourceAdapter, FetchContext]]) -> list[list[Batch] | Exception]:
    async with make_client() as client:
        async def one(adapter, ctx):
            try:
                return await adapter.fetch(client, ctx)
            except Exception as e:  # noqa: BLE001 - a source failure must never stop the others
                log.warning("source failed", extra={"ctx": {"source": adapter.key, "error": repr(e)}})
                return e
        return await asyncio.gather(*(one(a, c) for a, c in pairs))


def run_discovery(db: Session, only: list[str] | None = None, force: bool = False) -> dict:
    sources = ensure_sources(db)
    pairs: list[tuple[SourceAdapter, FetchContext]] = []
    skipped: dict[str, str] = {}
    for key, cls in ADAPTERS.items():
        src = sources[key]
        adapter = cls()
        if only and key not in only:
            continue
        if not src.enabled:
            skipped[key] = "disabled"
        elif not adapter.is_configured():
            skipped[key] = "not configured"
        elif not _is_due(src, force):
            skipped[key] = "not due"
        else:
            ctx = _build_context(db, adapter)
            if adapter.kind == "ats" and not ctx.boards:
                skipped[key] = "no company boards"
                continue
            pairs.append((adapter, ctx))

    results = asyncio.run(_fetch_all(pairs)) if pairs else []
    summary: dict = {"sources": {}, "skipped": skipped, "failing_sources": []}
    company_cache: dict[str, Company] = {c.normalized_name: c for c in db.scalars(select(Company))}
    for (adapter, _), result in zip(pairs, results, strict=True):
        src = sources[adapter.key]
        src.last_run_at = utcnow()
        agg = {"new": 0, "updated": 0, "closed": 0, "excluded": 0, "duplicates": 0, "errors": []}
        if isinstance(result, Exception):
            agg["errors"].append(f"{type(result).__name__}: {result}"[:500])
            batches = []
        else:
            batches = result
        for batch in batches:
            if batch.dead and batch.company_id:
                c = db.get(Company, batch.company_id)
                if c:
                    c.board_enabled, c.board_error = False, batch.error
            if batch.error:
                agg["errors"].append(f"{batch.scope or ''} {batch.error}".strip()[:300])
                if batch.dead or not batch.jobs:
                    continue
            for k, v in ingest_batch(db, src, batch, company_cache).items():
                agg[k] += v
        total_fail = isinstance(result, Exception) or (batches and all(b.error for b in batches))
        src.last_status = "failed" if total_fail else ("partial" if agg["errors"] else "ok")
        src.last_error = "; ".join(agg["errors"][:5]) or None
        src.consecutive_failures = (src.consecutive_failures or 0) + 1 if total_fail else 0
        src.jobs_found_total = (src.jobs_found_total or 0) + agg["new"]
        if src.consecutive_failures >= 3:
            summary["failing_sources"].append(src.key)
        agg["errors"] = agg["errors"][:10]
        summary["sources"][adapter.key] = agg
        db.commit()
    summary["new_total"] = sum(s["new"] for s in summary["sources"].values())
    return summary
