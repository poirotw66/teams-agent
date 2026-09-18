"""Register all quality API routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from .candidates import register_candidate_routes
from .cases import register_case_routes, register_observation_routes
from .clusters import register_cluster_routes
from .content import register_content_routes
from .context import QualityRouteContext
from .gaps import register_gap_routes


def register_quality_routes(
    app: FastAPI,
    *,
    resolved_settings: Any,
    query_service: Any,
    quality_service: Any,
    faq_service: Any,
    knowledge_client: Any,
    quality_metrics_by_issue: Callable[..., Any],
    enrich_quality_issue_display: Callable[[dict[str, Any]], dict[str, Any]],
    evaluation_service: Any = None,
    evaluation_run_service: Any = None,
    quality_gate_service: Any = None,
    current_actor: Callable[..., Any],
    require_capability: Callable[[Any, str], None],
) -> None:
    """Register HTTP routes for quality cases, candidates, gaps, and clusters."""
    ctx = QualityRouteContext(
        resolved_settings=resolved_settings,
        query_service=query_service,
        quality_service=quality_service,
        faq_service=faq_service,
        knowledge_client=knowledge_client,
        quality_metrics_by_issue=quality_metrics_by_issue,
        enrich_quality_issue_display=enrich_quality_issue_display,
        current_actor=current_actor,
        require_capability=require_capability,
        evaluation_service=evaluation_service,
        evaluation_run_service=evaluation_run_service,
        quality_gate_service=quality_gate_service,
    )
    register_case_routes(app, ctx)
    register_content_routes(app, ctx)
    register_observation_routes(app, ctx)
    register_candidate_routes(app, ctx)
    register_gap_routes(app, ctx)
    register_cluster_routes(app, ctx)
