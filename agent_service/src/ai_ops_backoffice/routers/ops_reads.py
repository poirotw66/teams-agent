from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from .analytics_router import (
    ALLOWED_EXPORT_FORMATS,
    EXPORT_CAPABILITIES,
    register_analytics_routes,
)
from .conversations_router import register_conversations_routes
from .ops_health_auth_routes import register_ops_health_auth_routes
from .sources_router import parse_range_header, register_sources_routes

__all__ = [
    "ALLOWED_EXPORT_FORMATS",
    "EXPORT_CAPABILITIES",
    "parse_range_header",
    "register_analytics_routes",
    "register_conversations_routes",
    "register_ops_read_routes",
    "register_sources_routes",
]


def register_ops_read_routes(
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
    """Register all operational read routes by delegating to modularized sub-routers."""
    register_ops_health_auth_routes(
        app,
        resolved_settings=resolved_settings,
        current_actor=current_actor,
    )
    register_conversations_routes(
        app,
        query_service=query_service,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
    )
    register_sources_routes(
        app,
        query_service=query_service,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
    )
    register_analytics_routes(
        app,
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
