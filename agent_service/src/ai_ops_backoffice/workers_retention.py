"""Scheduled cross-domain retention sweep for AI Ops workers."""

from __future__ import annotations

import logging
from typing import Any

from operations_core.access import ActorContext

logger = logging.getLogger(__name__)

__all__ = ["run_scheduled_retention_sweep"]


async def run_scheduled_retention_sweep(
    *,
    actor: ActorContext,
    query_service,
    sync_service=None,
    budget_service=None,
    example_service=None,
    quality_service=None,
    governance_service=None,
) -> dict[str, Any]:
    """Execute one cross-domain retention sweep using ACTIVE policy TTLs.

    Extracted from the lifespan worker so scheduled behavior is unit-testable
    without waiting for the background interval.
    """
    from .retention_runtime import resolve_active_retention_ttls

    ttls = resolve_active_retention_ttls(governance_service)
    retention_days = int(ttls["retention_days"])
    audit_retention_days = int(ttls["audit_retention_days"])

    events_res = await query_service.purge_expired_events()
    export_removed = 0
    if hasattr(query_service, "export_jobs") and query_service.export_jobs:
        export_removed = await query_service.export_jobs.purge_expired_jobs()

    examples_res = (
        example_service.purge_expired(actor=actor, retention_days=retention_days)
        if example_service
        else {"removed": 0}
    )
    quality_res = (
        quality_service.purge_expired(actor=actor, retention_days=retention_days)
        if quality_service
        else {"total": 0}
    )
    sync_res = (
        sync_service.purge_expired(actor=actor, retention_days=retention_days)
        if sync_service
        else {"total": 0}
    )
    budget_res = (
        budget_service.purge_expired(actor=actor, retention_days=retention_days)
        if budget_service
        else {"total": 0}
    )
    gov_res = (
        governance_service.purge_expired(
            actor=actor,
            retention_days=retention_days,
            audit_retention_days=audit_retention_days,
        )
        if governance_service is not None and hasattr(governance_service, "purge_expired")
        else {"totalRemoved": 0}
    )

    result = {
        "retentionDays": retention_days,
        "auditRetentionDays": audit_retention_days,
        "policy": ttls.get("policy"),
        "operationalEvents": events_res.get("removed", 0) if isinstance(events_res, dict) else 0,
        "exportJobs": export_removed,
        "examples": examples_res.get("removed", 0) if isinstance(examples_res, dict) else 0,
        "quality": quality_res.get("total", 0) if isinstance(quality_res, dict) else 0,
        "sync": sync_res.get("total", 0) if isinstance(sync_res, dict) else 0,
        "budget": budget_res.get("total", 0) if isinstance(budget_res, dict) else 0,
        "governance": gov_res,
    }
    logger.info(
        "Scheduled cross-domain retention sweep completed successfully "
        "(retentionDays=%s auditRetentionDays=%s).",
        retention_days,
        audit_retention_days,
    )
    return result
