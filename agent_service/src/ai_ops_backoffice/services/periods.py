from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent_service.operations.contracts import utc_now


@dataclass(frozen=True)
class ResolvedPeriod:
    days: int
    preset: str
    start_at: datetime
    end_at: datetime


PRESET_DAYS = {
    "today": 1,
    "7d": 7,
    "30d": 30,
    "month": 30,
    "180d": 180,
    "6m": 180,
}


def resolve_period(
    *,
    preset: str | None = None,
    days: int | None = None,
) -> ResolvedPeriod:
    normalized = (preset or "").strip().lower()
    if normalized in PRESET_DAYS:
        resolved_days = PRESET_DAYS[normalized]
        label = normalized
    else:
        resolved_days = days if days is not None else 7
        label = "custom"
    end_at = utc_now()
    start_at = end_at - timedelta(days=resolved_days)
    return ResolvedPeriod(
        days=resolved_days,
        preset=label,
        start_at=start_at,
        end_at=end_at,
    )


def event_in_period(
    occurred_at: datetime,
    period: ResolvedPeriod,
) -> bool:
    occurred = occurred_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    return occurred >= period.start_at
