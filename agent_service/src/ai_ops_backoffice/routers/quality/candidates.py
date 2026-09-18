"""Quality candidate list, refresh, and merge routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from ...request_models import QualityCandidateMergeRequest, QualityCandidateRefreshRequest
from .context import QualityRouteContext


def register_candidate_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    quality_service = ctx.quality_service
    query_service = ctx.query_service
    enrich_display = ctx.enrich_quality_issue_display

    @app.get("/api/quality-candidates")
    async def list_quality_candidates(
        status: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = [
            enrich_display(item)
            for item in quality_service.list_candidates(actor=actor, status=status)
        ]
        return {"items": items, "total": len(items)}

    @app.post("/api/quality-candidates/refresh")
    async def refresh_quality_candidates(
        payload: QualityCandidateRefreshRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        seeds = await query_service.quality_candidate_seeds(actor, days=payload.days)
        for seed in seeds:
            quality_service.add_candidate(**seed, actor=actor)
        items = quality_service.list_candidates(actor=actor, status="OPEN")
        return {"items": items, "total": len(items), "scanned": len(seeds)}

    @app.post("/api/quality-candidates/merge")
    async def merge_quality_candidates(
        payload: QualityCandidateMergeRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.merge_candidates(
            payload.candidate_ids,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            assignee_id=payload.assignee_id,
            target_due_at=payload.target_due_at,
            actor=actor,
        )
