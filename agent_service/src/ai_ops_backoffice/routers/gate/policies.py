"""Gate policy CRUD routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from operations_core.access import ActorContext

from .context import GateRouteContext
from .models import CreateGatePolicyPayload


def register_policy_routes(router: APIRouter, ctx: GateRouteContext) -> None:
    gate_service = ctx.gate_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.get("/gate-policies")
    async def list_gate_policies(actor: ActorContext = Depends(current_actor)) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        policies = gate_service.repository.list_policies()
        return [p.model_dump(mode="json") for p in policies]

    @router.post("/gate-policies")
    async def create_gate_policy(
        payload: CreateGatePolicyPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        tenant_id = actor.tenant_id or "default"
        pol, ver = gate_service.create_policy(
            policy_id=payload.policy_id,
            tenant_id=tenant_id,
            name=payload.name,
            created_by=actor.user_id,
            description=payload.description,
            mode=payload.mode,
            minimum_coverage=payload.minimum_coverage,
            minimum_pass_rate=payload.minimum_pass_rate,
            max_regression_count=payload.max_regression_count,
            required_set_version_ids=payload.required_set_version_ids,
        )
        return {
            "policy": pol.model_dump(mode="json"),
            "version": ver.model_dump(mode="json"),
        }

    @router.get("/gate-policies/{policy_id}")
    async def get_gate_policy(
        policy_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        policy = gate_service.repository.get_policy(policy_id)
        if not policy:
            return {"error": f"Gate policy '{policy_id}' not found"}
        versions = gate_service.repository.list_versions(policy_id)
        return {
            "policy": policy.model_dump(mode="json"),
            "versions": [v.model_dump(mode="json") for v in versions],
        }
