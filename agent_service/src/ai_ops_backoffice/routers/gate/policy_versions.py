"""Gate policy version lifecycle routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from agent_service.operations.access import ActorContext

from .context import GateRouteContext
from .models import ActivatePolicyVersionPayload, CreatePolicyVersionPayload


def register_policy_version_routes(router: APIRouter, ctx: GateRouteContext) -> None:
    gate_service = ctx.gate_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.post("/gate-policies/{policy_id}/versions")
    async def create_policy_version(
        policy_id: str,
        payload: CreatePolicyVersionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        version = gate_service.create_policy_version(
            policy_id=policy_id,
            name=payload.name,
            created_by=actor.user_id,
            description=payload.description,
            mode=payload.mode,
            minimum_coverage=payload.minimum_coverage,
            minimum_pass_rate=payload.minimum_pass_rate,
            max_regression_count=payload.max_regression_count,
            required_set_version_ids=payload.required_set_version_ids,
        )
        return {"version": version.model_dump(mode="json")}

    @router.post("/gate-policies/{policy_id}/versions/{version}/approve")
    async def approve_policy_version(
        policy_id: str,
        version: int,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.review")
        approved = gate_service.approve_policy_version(
            policy_id=policy_id,
            version=version,
            approved_by=actor.user_id,
        )
        return {"version": approved.model_dump(mode="json")}

    @router.post("/gate-policies/{policy_id}/versions/{version}/activate")
    async def activate_policy_version(
        policy_id: str,
        version: int,
        payload: ActivatePolicyVersionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.gates.manage")
        activated = gate_service.activate_policy_version(
            policy_id=policy_id,
            version=version,
            mode=payload.mode,
            actor=actor,
        )
        return {"version": activated.model_dump(mode="json")}
