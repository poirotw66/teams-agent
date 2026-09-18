"""Schedule timing helpers for evaluation dispatch."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .gate_models import ScheduleFrequency


def compute_next_due_time(
    current_due: datetime,
    frequency: ScheduleFrequency,
    tz_name: str = "UTC",
) -> datetime:
    """Calculates the next due datetime in UTC, preserving local wall-clock time across DST transitions (Spec 7.2)."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    local_dt = current_due.astimezone(tz)

    if frequency == "HOURLY":
        next_local = local_dt + timedelta(hours=1)
    elif frequency == "DAILY":
        next_date = local_dt.date() + timedelta(days=1)
        next_local = datetime.combine(next_date, local_dt.time(), tzinfo=tz)
    elif frequency == "WEEKLY":
        next_date = local_dt.date() + timedelta(weeks=1)
        next_local = datetime.combine(next_date, local_dt.time(), tzinfo=tz)
    elif frequency == "ON_CHANGE":
        return current_due
    else:
        next_date = local_dt.date() + timedelta(days=1)
        next_local = datetime.combine(next_date, local_dt.time(), tzinfo=tz)

    return next_local.astimezone(timezone.utc)
