"""Health, audit-event, and feedback list routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from .context import AnalyticsRouteContext


def register_observability_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service

    @app.get("/api/health/summary")
    async def health_summary(
        date: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.health.read")
        return await query_service.health_summary(target_date=date)

    @app.get("/api/audit-events")
    async def audit_events(
        actor_id: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.audit.read")
        items, next_cursor = await query_service.audit_store.list_events(
            cursor=cursor,
            limit=limit,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            start_date=start_date,
            end_date=end_date,
        )
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "nextCursor": next_cursor,
            "hasMore": next_cursor is not None,
        }

    @app.get("/api/feedback")
    async def feedback_list(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        rating: str | None = None,
        issue_type_id: str | None = None,
        reason: str | None = None,
        resolved_status: str | None = Query(default=None, alias="resolved"),
        handoff: bool | None = None,
        model: str | None = None,
        route: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.feedback.read")
        return await query_service.list_feedback(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            rating=rating,
            issue_type_id=issue_type_id,
            reason=reason,
            resolved_status=resolved_status,
            handoff=handoff,
            model=model,
            route=route,
            limit=limit,
            cursor=cursor,
        )
