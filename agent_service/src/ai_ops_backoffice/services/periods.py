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
    explicit_range: bool = False


PRESET_DAYS = {
    "today": 1,
    "7d": 7,
    "30d": 30,
    "month": 30,
    "180d": 180,
    "6m": 180,
}


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def resolve_period(
    *,
    preset: str | None = None,
    days: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ResolvedPeriod:
    if start_date:
        start_at = _parse_iso_datetime(start_date)
        end_at = _parse_iso_datetime(end_date) if end_date else utc_now()
        resolved_days = max(1, int((end_at - start_at).total_seconds() // 86400) + 1)
        return ResolvedPeriod(
            days=resolved_days,
            preset="custom",
            start_at=start_at,
            end_at=end_at,
            explicit_range=True,
        )

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
    if period.explicit_range:
        return period.start_at <= occurred <= period.end_at
    return occurred >= period.start_at
