"""Cost summary route."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from .context import AnalyticsRouteContext


def register_cost_summary_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    audit_read = ctx.audit_read

    @app.get("/api/costs/summary")
    async def costs_summary(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        model: str | None = None,
        refresh: bool = False,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.cost.read")
        result = await query_service.costs_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            model=model,
            force_refresh=refresh,
        )
        await audit_read(
            actor,
            "query.costs_summary",
            "costs_summary",
            after={
                "days": days,
                "preset": preset,
                "startDate": start_date,
                "endDate": end_date,
                "model": model,
            },
        )
        return result
