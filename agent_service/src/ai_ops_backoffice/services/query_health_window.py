"""Taipei calendar-day window resolution for health historical queries."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from operations_core.contracts import DEFAULT_TIMEZONE


def resolve_taipei_day_window(target_date: str) -> tuple[datetime, datetime, date]:
    """Resolve a calendar day in Asia/Taipei regardless of input timezone offsets.

    Health historical queries must match other ops day boundaries (Taipei), so a
    UTC midnight ISO string still maps to the Taipei calendar date it represents.
    """
    raw = target_date.strip()
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    if "T" in raw:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            local_day = parsed.date()
        else:
            local_day = parsed.astimezone(tz).date()
    else:
        local_day = date.fromisoformat(raw[:10])
    local_start = datetime(local_day.year, local_day.month, local_day.day, 0, 0, 0, 0, tzinfo=tz)
    window_start = local_start.astimezone(UTC)
    window_end = (local_start + timedelta(days=1)).astimezone(UTC)
    return window_start, window_end, local_day
