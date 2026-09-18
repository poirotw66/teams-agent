"""Golden evaluation candidate-generation job routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from operations_core.access import ActorContext

from .context import EvaluationRouteContext
from .models import CandidateJobPayload


def register_candidate_routes(router: APIRouter, ctx: EvaluationRouteContext) -> None:
    candidate_manager = ctx.candidate_manager
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.post("/candidate-jobs", status_code=202)
    async def start_candidate_job(
        payload: CandidateJobPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        job = candidate_manager.start_generation_job(
            source_refs=tuple(payload.source_refs),
            target_types=tuple(payload.target_types),
            requested_count=payload.requested_count,
            owner_unit_id=payload.owner_unit_id,
            actor=actor,
            limits=payload.limits,
        )
        return job

    @router.get("/candidate-jobs/{job_id}")
    async def get_candidate_job(
        job_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return candidate_manager.get_job_status(job_id, actor=actor)

    @router.post("/candidate-jobs/{job_id}/cancel")
    async def cancel_candidate_job(
        job_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return candidate_manager.cancel_job(job_id, actor=actor)
