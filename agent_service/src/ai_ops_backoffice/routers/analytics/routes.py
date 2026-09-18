"""Register all analytics API routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from .catalog import register_catalog_routes
from .context import AnalyticsRouteContext
from .costs import register_cost_summary_routes
from .exports import register_export_routes
from .issues import register_issue_routes, register_routes_summary_routes
from .knowledge import register_knowledge_routes
from .observability import register_observability_routes
from .operations import register_aggregate_routes, register_operations_routes
from .pricing import register_pricing_routes
from .reconciliation import register_reconciliation_routes
from .retention import register_retention_routes


def register_analytics_routes(
    app: FastAPI,
    *,
    resolved_settings: Any,
    query_service: Any,
    governance_service: Any,
    current_actor: Callable[..., Any],
    require_capability: Callable[[Any, str], None],
    audit_read: Callable[..., Any],
    export_rate_limiter: Any,
    example_service: Any = None,
    quality_service: Any = None,
    sync_service: Any = None,
    budget_service: Any = None,
) -> None:
    """Register HTTP routes for analytics, costs, issues, reconciliations, exports, and retention."""
    ctx = AnalyticsRouteContext(
        resolved_settings=resolved_settings,
        query_service=query_service,
        governance_service=governance_service,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
        export_rate_limiter=export_rate_limiter,
        example_service=example_service,
        quality_service=quality_service,
        sync_service=sync_service,
        budget_service=budget_service,
    )
    register_catalog_routes(app, ctx)
    register_operations_routes(app, ctx)
    register_aggregate_routes(app, ctx)
    register_issue_routes(app, ctx)
    register_routes_summary_routes(app, ctx)
    register_cost_summary_routes(app, ctx)
    register_pricing_routes(app, ctx)
    register_observability_routes(app, ctx)
    register_reconciliation_routes(app, ctx)
    register_knowledge_routes(app, ctx)
    register_retention_routes(app, ctx)
    register_export_routes(app, ctx)
