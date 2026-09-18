"""Golden evaluation case list, create, detail, and retire routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query

from operations_core.access import ActorContext

from .case_create import build_create_case_kwargs
from .context import EvaluationRouteContext
from .models import CaseCreatePayload, RetireCasePayload


def register_case_routes(router: APIRouter, ctx: EvaluationRouteContext) -> None:
    evaluation_service = ctx.evaluation_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.get("/cases")
    async def list_cases(
        q: str | None = None,
        owner_unit_id: str | None = None,
        status: str | None = None,
        behavior: str | None = None,
        criticality: str | None = None,
        source_health: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        items = evaluation_service.list_cases(
            actor=actor,
            q=q,
            owner_unit_id=owner_unit_id,
            status=status,
            behavior=behavior,
            criticality=criticality,
            source_health=source_health,
            source_type=source_type,
            source_id=source_id,
            limit=limit,
        )
        return {"items": items, "total": len(items)}

    @router.post("/cases", status_code=201)
    async def create_case(
        payload: CaseCreatePayload,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.create_case(
            **build_create_case_kwargs(
                payload,
                actor=actor,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )

    @router.get("/cases/{case_id}")
    async def get_case(
        case_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return evaluation_service.get_case_detail(case_id, actor=actor)

    @router.post("/cases/{case_id}/retire")
    async def retire_case(
        case_id: str,
        payload: RetireCasePayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.retire_case(
            case_id,
            reason=payload.reason,
            actor=actor,
            correlation_id=correlation_id,
        )
