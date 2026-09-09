"""Resolve ACTIVE retention TTLs for scheduled and manual purge paths."""

from __future__ import annotations

from typing import Any


DEFAULT_RETENTION_DAYS = 365
DEFAULT_AUDIT_RETENTION_DAYS = 1095


def resolve_active_retention_ttls(
    governance_service: Any | None,
    *,
    default_retention_days: int = DEFAULT_RETENTION_DAYS,
    default_audit_retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS,
) -> dict[str, Any]:
    """Return retention TTLs from ACTIVE operational-events policy when present.

    Audit records use a longer default (typically 3 years) and never shorter
    than the operational retention window.
    """
    peeked = None
    if governance_service is not None and hasattr(governance_service, "peek_runtime_retention"):
        peeked = governance_service.peek_runtime_retention("operational-events")

    retention_days = default_retention_days
    if isinstance(peeked, dict) and peeked.get("ttlDays") is not None:
        try:
            retention_days = max(1, int(peeked["ttlDays"]))
        except (TypeError, ValueError):
            retention_days = default_retention_days

    audit_retention_days = max(retention_days, int(default_audit_retention_days))
    return {
        "retention_days": retention_days,
        "audit_retention_days": audit_retention_days,
        "policy": peeked,
    }
