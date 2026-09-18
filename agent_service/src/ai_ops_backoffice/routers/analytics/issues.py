"""Issue summary and per-issue route endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from .context import AnalyticsRouteContext


def register_issue_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    audit_read = ctx.audit_read

    @app.get("/api/issues/summary")
    async def issues_summary(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        query: str | None = None,
        owner_unit_id: str | None = None,
        refresh: bool = False,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        result = await query_service.issues_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            query=query,
            owner_unit_id=owner_unit_id,
            force_refresh=refresh,
        )
        await audit_read(
            actor,
            "query.issues_summary",
            "issues_summary",
            after={
                "days": days,
                "preset": preset,
                "query": query,
                "ownerUnitId": owner_unit_id,
                "resultCount": len(result.get("items") or []),
            },
        )
        return result

    @app.get("/api/issues/{issue_type_id}/routes")
    async def issue_routes(
        issue_type_id: str,
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        result = await query_service.issue_routes(
            actor,
            issue_type_id,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(actor, "query.issue_routes", issue_type_id)
        return result


def register_routes_summary_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    audit_read = ctx.audit_read

    @app.get("/api/routes/summary")
    async def routes_summary(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
        route: str | None = None,
        refresh: bool = False,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        result = await query_service.routes_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            issue_type_id=issue_type_id,
            route=route,
            force_refresh=refresh,
        )
        await audit_read(actor, "query.routes_summary", "routes_summary")
        return result
