"""Register all FAQ API routes."""

from __future__ import annotations

from fastapi import FastAPI

from .context import FaqRouteContext
from .lifecycle import register_faq_lifecycle_routes
from .reads import register_faq_read_routes
from .reviews import register_faq_review_routes
from .writes import register_faq_write_routes


def register_faq_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    faq_service,
    quality_service,
    quality_metrics_by_issue,
    current_actor,
    require_capability,
    audit_read,
) -> None:
    """Register HTTP routes for FAQ reads, writes, and lifecycle transitions."""
    ctx = FaqRouteContext(
        resolved_settings=resolved_settings,
        query_service=query_service,
        faq_service=faq_service,
        quality_service=quality_service,
        quality_metrics_by_issue=quality_metrics_by_issue,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
    )
    register_faq_read_routes(app, ctx)
    register_faq_write_routes(app, ctx)
    register_faq_review_routes(app, ctx)
    register_faq_lifecycle_routes(app, ctx)
