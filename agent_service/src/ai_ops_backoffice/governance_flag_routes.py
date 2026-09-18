"""Feature-flag route registration for governance."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Query

from .governance_domain import GovernanceService
from .governance_route_models import FlagCandidateBody, ReasonBody

__all__ = ["register_flag_routes"]


def register_flag_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
) -> None:
    @app.get("/api/governance/flags")
    async def list_governance_flags(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.flags.read")
        return {"items": governance.list_flags(actor=actor)}

    @app.post("/api/governance/flags/candidates")
    async def create_governance_flag(
        payload: FlagCandidateBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.flags.write")
        return governance.create_flag_candidate(**payload.model_dump(), actor=actor)

    @app.post("/api/governance/flags/{flag_id}/versions/{version_id}/approve")
    async def approve_governance_flag(
        flag_id: str, version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.flags.approve")
        return governance.approve_flag(
            flag_id=flag_id, version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/flags/{flag_id}/versions/{version_id}/activate")
    async def activate_governance_flag(
        flag_id: str, version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.flags.activate")
        return governance.activate_flag(
            flag_id=flag_id, version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.get("/api/governance/flags/{flag_id}/effective")
    async def effective_governance_flag(
        flag_id: str,
        environment: str = Query(default="lab"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.flags.read")
        return governance.effective_flag(flag_id, actor=actor, environment=environment)
