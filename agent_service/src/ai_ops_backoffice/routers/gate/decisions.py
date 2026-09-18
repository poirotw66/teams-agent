"""Gate decision and exception routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from operations_core.access import ActorContext

from .context import GateRouteContext
from .models import EvaluateDecisionPayload, RequestExceptionPayload


def register_decision_routes(router: APIRouter, ctx: GateRouteContext) -> None:
    gate_service = ctx.gate_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.post("/gate-decisions")
    async def evaluate_decision(
        payload: EvaluateDecisionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        decision = gate_service.evaluate_decision(
            policy_id=payload.policy_id,
            policy_version=payload.policy_version,
            run_id=payload.run_id,
            target_manifest_hash=payload.target_manifest_hash,
            actor=actor,
        )
        return {"decision": decision.model_dump(mode="json")}

    @router.get("/gate-decisions")
    async def list_decisions(
        target_manifest_hash: str | None = Query(default=None),
        actor: ActorContext = Depends(current_actor),
    ) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        decisions = gate_service.repository.list_decisions(target_manifest_hash=target_manifest_hash)
        return [d.model_dump(mode="json") for d in decisions]

    @router.get("/gate-decisions/{decision_id}")
    async def get_decision(
        decision_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        decision = gate_service.repository.get_decision(decision_id)
        if not decision:
            return {"error": f"Gate decision '{decision_id}' not found"}
        return {"decision": decision.model_dump(mode="json")}

    @router.post("/gate-decisions/{decision_id}/exceptions")
    async def request_exception(
        decision_id: str,
        payload: RequestExceptionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        exc = gate_service.request_exception(
            decision_id=decision_id,
            reason=payload.reason,
            requested_by=actor.user_id,
            validity_hours=payload.validity_hours,
        )
        return {"exception": exc.model_dump(mode="json")}

    @router.post("/exceptions/{exception_id}/approve")
    async def approve_exception(
        exception_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.gates.manage")
        approved = gate_service.approve_exception(
            exception_id=exception_id,
            approver_id=actor.user_id,
        )
        return {"exception": approved.model_dump(mode="json")}
