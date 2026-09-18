"""Role-change route registration for governance."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from .governance_domain import GovernanceService
from .governance_route_models import ReasonBody, RevokeBody, RoleRequestBody

__all__ = ["register_role_routes"]


def register_role_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
) -> None:
    @app.get("/api/governance/roles")
    async def list_role_changes(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.roles.read")
        return {"items": governance.list_role_changes(actor=actor)}

    @app.post("/api/governance/roles/requests")
    async def request_role_change(
        payload: RoleRequestBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.roles.request")
        return governance.request_role_change(**payload.model_dump(), actor=actor)

    @app.post("/api/governance/roles/{change_id}/approve")
    async def approve_role_change(
        change_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.roles.approve")
        return governance.approve_role_change(
            change_id=change_id, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/roles/revoke")
    async def revoke_principal(
        payload: RevokeBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.roles.revoke")
        return governance.revoke_principal(
            principal=payload.principal, reason=payload.reason, actor=actor
        )
