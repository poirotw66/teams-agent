"""Operations summary and daily-aggregate routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from .context import AnalyticsRouteContext


def _apply_cost_display_flag(
    result: dict[str, object],
    *,
    resolved_settings: Any,
    governance_service: Any,
) -> dict[str, object]:
    project = (resolved_settings.gcp_project_id or "").lower()
    environment = "prod" if "prod" in project else "lab"
    cost_flag = governance_service.peek_runtime_flag(
        "cost_display", environment=environment
    )
    cost_enabled = True
    if cost_flag is not None:
        cost_enabled = str(cost_flag.get("value") or "").lower() in {
            "true",
            "1",
            "enabled",
        }
    if not cost_enabled:
        return {
            **result,
            "estimatedCostUsd": None,
            "costCoverage": None,
            "costDisplayEnabled": False,
        }
    return {**result, "costDisplayEnabled": True}


def register_operations_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    governance_service = ctx.governance_service
    audit_read = ctx.audit_read
    resolved_settings = ctx.resolved_settings

    @app.get("/api/operations/summary")
    async def operations_summary(
        days: int = Query(default=7, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        model: str | None = None,
        issue_type_id: str | None = None,
        interval: str = Query(default="DAY"),
        refresh: bool = False,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        result = await query_service.operations_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            model=model,
            issue_type_id=issue_type_id,
            interval=interval,
            force_refresh=refresh,
        )
        result = _apply_cost_display_flag(
            result,
            resolved_settings=resolved_settings,
            governance_service=governance_service,
        )
        await audit_read(
            actor,
            "query.operations_summary",
            "operations_summary",
            after={
                "days": days,
                "preset": preset,
                "startDate": start_date,
                "endDate": end_date,
                "model": model,
                "issueTypeId": issue_type_id,
                "interval": interval,
            },
        )
        return result


def register_aggregate_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    audit_read = ctx.audit_read

    @app.get("/api/aggregates/summary")
    async def aggregates_summary(
        days: int = Query(default=7, ge=1, le=365),
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        result = await query_service.daily_aggregates_summary(actor, days=days)
        await audit_read(
            actor,
            "query.aggregates_summary",
            "daily_aggregates",
            after={"days": days},
        )
        return result

    @app.post("/api/aggregates/rebuild")
    async def aggregates_rebuild(
        days: int = Query(default=30, ge=1, le=365),
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        result = await query_service.rebuild_daily_aggregates(days=days)
        await audit_read(
            actor,
            "query.aggregates_rebuild",
            "daily_aggregates",
            after={"days": days, "written": result.get("written")},
        )
        return result
