"""Gate release verification and target activation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from operations_core.access import ActorContext

from ...evaluation_domain.runner_models import TargetManifest
from .context import GateRouteContext
from .models import ActivateTargetPayload, CreateQualityCasePayload, VerifyReleasePayload


def register_release_routes(router: APIRouter, ctx: GateRouteContext) -> None:
    gate_service = ctx.gate_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.post("/verify-release")
    async def verify_release(
        payload: VerifyReleasePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return gate_service.verify_release_gate(
            target_manifest_hash=payload.target_manifest_hash,
            policy_id=payload.policy_id,
            tenant_id=actor.tenant_id,
        )

    @router.post("/runs/{run_id}/cases/{execution_id}/quality-case")
    async def link_quality_case(
        run_id: str,
        execution_id: str,
        payload: CreateQualityCasePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        case_link = gate_service.link_quality_case(
            run_id=run_id,
            execution_id=execution_id,
            root_cause=payload.root_cause,
            actor=actor,
        )
        return {"quality_case": case_link.model_dump(mode="json")}

    @router.post("/activate-target")
    async def activate_target(
        payload: ActivateTargetPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        manifest = TargetManifest.model_validate(payload.candidate_manifest)
        pointer = gate_service.activate_target(
            tenant_id=actor.tenant_id or "default",
            environment=payload.environment,
            target_type=payload.target_type,
            candidate_manifest=manifest,
            active_version_ref=payload.active_version_ref,
            actor=actor,
            policy_id=payload.policy_id,
            expected_pointer_etag=payload.expected_pointer_etag,
            break_glass_id=payload.break_glass_id,
        )
        return {"pointer": pointer.model_dump(mode="json")}
