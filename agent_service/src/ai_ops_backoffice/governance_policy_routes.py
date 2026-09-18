"""Retention and masking policy route registration for governance."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from .governance_domain import GovernanceService
from .governance_route_models import MaskingBody, ReasonBody, RetentionBody

__all__ = ["register_policy_routes"]


def register_retention_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
) -> None:
    @app.post("/api/governance/retention/candidates")
    async def create_retention(
        payload: RetentionBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.create_retention_candidate(**payload.model_dump(), actor=actor)

    @app.get("/api/governance/retention")
    async def list_retention(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.retention.read")
        return {"items": governance.list_retention_policies(actor=actor)}

    @app.post("/api/governance/retention/{version_id}/approve")
    async def approve_retention(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.approve_retention(
            version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/retention/{version_id}/activate")
    async def activate_retention(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.activate_retention(
            version_id=version_id, reason=payload.reason, actor=actor
        )


def register_masking_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
) -> None:
    @app.get("/api/governance/masking")
    async def list_masking(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.retention.read")
        return {"items": governance.list_masking_policies(actor=actor)}

    @app.post("/api/governance/masking/candidates")
    async def create_masking(
        payload: MaskingBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.create_masking_candidate(**payload.model_dump(), actor=actor)

    @app.post("/api/governance/masking/{version_id}/approve")
    async def approve_masking(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.approve_masking(version_id=version_id, reason=payload.reason, actor=actor)

    @app.post("/api/governance/masking/{version_id}/activate")
    async def activate_masking(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.activate_masking(
            version_id=version_id, reason=payload.reason, actor=actor
        )


def register_policy_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
) -> None:
    register_retention_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_masking_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
    )
