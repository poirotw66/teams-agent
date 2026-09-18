"""Question-cluster list, generate, and correct routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from ...request_models import QuestionClusterCorrectionRequest
from .context import QualityRouteContext


def register_cluster_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    quality_service = ctx.quality_service

    @app.get("/api/question-clusters")
    async def list_question_clusters(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = quality_service.list_clusters(actor=actor)
        return {"items": items, "total": len(items)}

    @app.post("/api/question-clusters/generate")
    async def generate_question_clusters(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.generate_clusters(actor=actor)

    @app.post("/api/question-clusters/correct")
    async def correct_question_clusters(
        payload: QuestionClusterCorrectionRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.correct_clusters(
            payload.cluster_ids,
            action=payload.action,
            name=payload.name,
            candidate_groups=payload.candidate_groups,
            actor=actor,
        )
