from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from agent_service.operations.contracts import DEFAULT_TIMEZONE, utc_now


@dataclass(frozen=True)
class ResolvedPeriod:
    days: int
    preset: str
    start_at: datetime
    end_at: datetime
    explicit_range: bool = False


class PeriodPolicyError(ValueError):
    pass


MAX_PERIOD_DAYS = 186

PRESET_DAYS = {
    "today": 1,
    "7d": 7,
    "30d": 30,
    "180d": 180,
    "6m": 180,
}


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _validate_span_days(resolved_days: int) -> None:
    if resolved_days > MAX_PERIOD_DAYS:
        raise PeriodPolicyError(
            f"Query period exceeds the maximum of {MAX_PERIOD_DAYS} days."
        )


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
        _validate_span_days(resolved_days)
        if end_at < start_at:
            raise PeriodPolicyError("end_date must be on or after start_date.")
        return ResolvedPeriod(
            days=resolved_days,
            preset="custom",
            start_at=start_at,
            end_at=end_at,
            explicit_range=True,
        )

    normalized = (preset or "").strip().lower()
    if normalized == "month":
        end_at = utc_now()
        local_now = end_at.astimezone(ZoneInfo(DEFAULT_TIMEZONE))
        start_at = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        resolved_days = max(1, (local_now.date() - start_at.date()).days + 1)
        return ResolvedPeriod(
            days=resolved_days,
            preset="month",
            start_at=start_at,
            end_at=end_at,
            explicit_range=True,
        )
    if normalized in PRESET_DAYS:
        resolved_days = PRESET_DAYS[normalized]
        label = normalized
    else:
        resolved_days = days if days is not None else 7
        label = "custom"
    _validate_span_days(resolved_days)
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
