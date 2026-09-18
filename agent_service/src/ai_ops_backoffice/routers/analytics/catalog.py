"""Taxonomy and metrics-definition routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from .context import AnalyticsRouteContext


def register_catalog_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service

    @app.get("/api/taxonomy")
    async def taxonomy(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        return {
            "taxonomyVersion": query_service.taxonomy.version,
            "items": [item.model_dump() for item in query_service.taxonomy.list_active()],
        }

    @app.get("/api/metrics/definitions")
    async def metrics_definitions(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        return query_service.metrics_definitions()
