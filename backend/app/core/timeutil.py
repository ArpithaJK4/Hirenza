from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def hours_since(dt: datetime | None) -> float | None:
    dt = as_utc(dt)
    if dt is None:
        return None
    return max(0.0, (utcnow() - dt).total_seconds() / 3600)
