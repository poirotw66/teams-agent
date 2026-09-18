"""Golden evaluation set and set-version routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header

from agent_service.operations.access import ActorContext

from .context import EvaluationRouteContext
from .models import PublishSetVersionPayload, SetCreatePayload, SetVersionDraftPayload


def register_set_routes(router: APIRouter, ctx: EvaluationRouteContext) -> None:
    evaluation_service = ctx.evaluation_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.get("/sets")
    async def list_sets(
        purpose: Literal["DEVELOPMENT", "HOLDOUT"] | None = None,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        items = evaluation_service.list_sets(actor=actor, purpose=purpose)
        return {"items": items, "total": len(items)}

    @router.post("/sets", status_code=201)
    async def create_set(
        payload: SetCreatePayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.create_set(
            name=payload.name,
            owner_unit_ids=tuple(payload.owner_unit_ids),
            purpose=payload.purpose,
            description=payload.description,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.get("/sets/{set_id}")
    async def get_set(
        set_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return evaluation_service.get_set_detail(set_id, actor=actor)

    @router.post("/sets/{set_id}/versions", status_code=201)
    async def create_set_version_draft(
        set_id: str,
        payload: SetVersionDraftPayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.create_set_version_draft(
            set_id,
            case_revision_ids=tuple(payload.case_revision_ids),
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.post("/sets/{set_id}/versions/{version_id}/publish")
    async def publish_set_version(
        set_id: str,
        version_id: str,
        payload: PublishSetVersionPayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.sets.publish")
        return evaluation_service.publish_set_version(
            version_id,
            expected_etag=payload.expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )
