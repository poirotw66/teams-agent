"""Quality case list, detail, update, transition, and observation routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from ...request_models import (
    FaqTransitionRequest,
    QualityCaseTransitionRequest,
    QualityCaseUpdateRequest,
)
from .context import QualityRouteContext
from .evaluation import build_evaluation_context


def register_case_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    quality_service = ctx.quality_service
    enrich_display = ctx.enrich_quality_issue_display

    @app.get("/api/quality-cases")
    async def list_quality_cases(
        status: str | None = None,
        case_type: str | None = None,
        owner_unit_id: str | None = None,
        issue_type_id: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = [
            enrich_display(item)
            for item in quality_service.list_cases(
                actor=actor,
                status=status,
                case_type=case_type,
                owner_unit_id=owner_unit_id,
                issue_type_id=issue_type_id,
            )
        ]
        return {"items": items, "total": len(items)}

    @app.get("/api/quality-cases/{case_id}")
    async def get_quality_case(
        case_id: str,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        detail = quality_service.case_detail(case_id, actor=actor)
        return {
            **detail,
            "case": enrich_display(detail["case"]),
            **build_evaluation_context(ctx, case_id, actor),
        }

    @app.put("/api/quality-cases/{case_id}")
    async def update_quality_case(
        case_id: str,
        payload: QualityCaseUpdateRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.update_case(
            case_id,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            assignee_id=payload.assignee_id,
            target_due_at=payload.target_due_at,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.post("/api/quality-cases/{case_id}/transition")
    async def transition_quality_case(
        case_id: str,
        payload: QualityCaseTransitionRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        capability = (
            "ops.quality.resolve"
            if payload.status in {"RESOLVED", "WONT_FIX", "DUPLICATE"}
            else "ops.quality.write"
        )
        require_capability(actor, capability)
        return quality_service.transition_case(
            case_id,
            status=payload.status,
            reason=payload.reason,
            resolution_type=payload.resolution_type,
            expected_etag=payload.expected_etag,
            actor=actor,
        )


def register_observation_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    quality_service = ctx.quality_service
    quality_metrics_by_issue = ctx.quality_metrics_by_issue

    @app.post("/api/quality-cases/{case_id}/observation/refresh")
    async def refresh_quality_case_observation(
        case_id: str,
        payload: FaqTransitionRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        metrics = (await quality_metrics_by_issue(actor)).get(case["issue_type_id"] or "", {})
        return quality_service.record_observation(
            case_id,
            metrics=metrics,
            expected_etag=payload.expected_etag,
            actor=actor,
        )
