"""Audit query and export routes for governance."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Query

from .governance_domain import GovernanceService

__all__ = ["register_audit_routes"]


def register_audit_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
) -> None:
    @app.get("/api/governance/audit")
    async def governance_audit(
        actor_id: str | None = Query(default=None),
        action: str | None = Query(default=None),
        target_type: str | None = Query(default=None),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.audit.read")
        return governance.query_audit(
            actor=actor,
            target_type=target_type,
            actor_id=actor_id,
            action=action,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            cursor=cursor,
        )

    @app.get("/api/governance/audit/export")
    async def governance_audit_export(
        actor_id: str | None = Query(default=None),
        action: str | None = Query(default=None),
        target_type: str | None = Query(default=None),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.audit.read")
        return governance.export_audit(
            actor=actor,
            target_type=target_type,
            actor_id=actor_id,
            action=action,
            start_date=start_date,
            end_date=end_date,
        )
