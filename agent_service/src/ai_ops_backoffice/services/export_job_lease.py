"""Shared lease helpers for export job claim/ownership transitions."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any


def lease_expired(payload: dict[str, Any], now: datetime) -> bool:
    raw = payload.get("lease_expires_at")
    if not raw:
        return True
    if isinstance(raw, datetime):
        expires = raw
    else:
        expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return expires <= now


def apply_claim(
    payload: dict[str, Any],
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime,
) -> dict[str, Any]:
    claimed = dict(payload)
    claimed["status"] = "RUNNING"
    claimed["lease_owner"] = worker_id
    claimed["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
    claimed["lease_token"] = uuid.uuid4().hex
    claimed["attempt_count"] = int(claimed.get("attempt_count") or 0) + 1
    claimed["error"] = None
    return claimed


def clear_lease_fields(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    next_payload["lease_owner"] = None
    next_payload["lease_expires_at"] = None
    next_payload["lease_token"] = None
    return next_payload


def parse_firestore_timestamps(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert ISO timestamp strings to datetime for Firestore writes."""
    converted = dict(payload)
    for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
        value = converted.get(key)
        if isinstance(value, str):
            converted[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return converted


def serialize_firestore_timestamps(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert datetime timestamps back to ISO strings for callers."""
    result = dict(payload)
    for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
        value = result.get(key)
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def owns_running_lease(
    current: dict[str, Any],
    *,
    worker_id: str,
    lease_token: str,
) -> bool:
    if current.get("status") != "RUNNING":
        return False
    if current.get("lease_owner") != worker_id:
        return False
    return current.get("lease_token") == lease_token
