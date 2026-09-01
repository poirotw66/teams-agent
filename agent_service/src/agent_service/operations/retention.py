from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .contracts import utc_now
from .settings import OpsSettings


def retention_expiry(settings: OpsSettings, *, days: int | None = None) -> datetime:
    lifetime = days if days is not None else settings.default_retention_days
    return utc_now() + timedelta(days=lifetime)


def is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    current = utc_now()
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return current >= expires_at
