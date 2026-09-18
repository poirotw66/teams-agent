"""Register all source citation preview and file streaming routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from .context import SourcesRouteContext
from .file import register_file_routes
from .preview import register_preview_routes
from .resolve import register_resolve_routes


def register_sources_routes(
    app: FastAPI,
    *,
    query_service: Any,
    current_actor: Callable[..., Any],
    require_capability: Callable[[Any, str], None],
    audit_read: Callable[..., Any],
) -> None:
    """Register HTTP read routes for source citation preview and file streaming."""
    ctx = SourcesRouteContext(
        query_service=query_service,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
    )
    register_resolve_routes(app, ctx)
    register_preview_routes(app, ctx)
    register_file_routes(app, ctx)
