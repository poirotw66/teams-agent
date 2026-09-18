"""Golden evaluation case revision routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header

from agent_service.operations.access import ActorContext

from .context import EvaluationRouteContext
from .models import ReviewRevisionPayload, RevisionCreatePayload, SubmitRevisionPayload


def register_revision_routes(router: APIRouter, ctx: EvaluationRouteContext) -> None:
    evaluation_service = ctx.evaluation_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.post("/cases/{case_id}/revisions", status_code=201)
    async def create_revision(
        case_id: str,
        payload: RevisionCreatePayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.create_revision(
            case_id,
            query=payload.query,
            base_revision_id=payload.base_revision_id,
            behavior=payload.behavior,
            tags=tuple(payload.tags) if payload.tags is not None else None,
            criticality=payload.criticality,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.post("/cases/{case_id}/revisions/{revision_id}/submit")
    async def submit_revision(
        case_id: str,
        revision_id: str,
        payload: SubmitRevisionPayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.submit_revision(
            revision_id,
            expected_etag=payload.expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.post("/cases/{case_id}/revisions/{revision_id}/review")
    async def review_revision(
        case_id: str,
        revision_id: str,
        payload: ReviewRevisionPayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.review")
        return evaluation_service.review_revision(
            revision_id,
            approve=payload.approve,
            reason=payload.reason,
            expected_etag=payload.expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )
