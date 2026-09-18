"""Admin reconciliation routes for summary aggregates."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from ...services.reconciliation import (
    reconcile_costs_summary,
    reconcile_issues_summary,
    reconcile_operations_summary,
)
from .context import AnalyticsRouteContext


def register_reconciliation_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    audit_read = ctx.audit_read

    @app.get("/api/admin/reconciliation/operations-summary")
    async def reconciliation_operations_summary(
        days: int = Query(default=7, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        result = await reconcile_operations_summary(
            query_service,
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(
            actor,
            "reconciliation.operations_summary",
            "operations_summary",
            after={"allMatch": result["allMatch"]},
        )
        return result

    @app.get("/api/admin/reconciliation/costs-summary")
    async def reconciliation_costs_summary(
        days: int = Query(default=7, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        result = await reconcile_costs_summary(
            query_service,
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(
            actor,
            "reconciliation.costs_summary",
            "costs_summary",
            after={"allMatch": result["allMatch"]},
        )
        return result

    @app.get("/api/admin/reconciliation/issues-summary")
    async def reconciliation_issues_summary(
        days: int = Query(default=7, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        result = await reconcile_issues_summary(
            query_service,
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(
            actor,
            "reconciliation.issues_summary",
            "issues_summary",
            after={"allMatch": result["allMatch"]},
        )
        return result
