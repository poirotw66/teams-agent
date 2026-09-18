"""Register all console aggregation API routes."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from .context import ConsoleRouteContext
from .work_items import register_work_item_routes
from .workflows import register_workflow_routes


def register_console_routes(
    app: FastAPI,
    *,
    quality_service: Any = None,
    knowledge_client: Any = None,
    evaluation_service: Any = None,
    evaluation_run_service: Any = None,
    quality_gate_service: Any = None,
    current_actor: Any,
    require_capability: Any,
) -> None:
    """Register HTTP routes for console work items, summaries, and workflows."""
    ctx = ConsoleRouteContext(
        current_actor=current_actor,
        require_capability=require_capability,
        quality_service=quality_service,
        knowledge_client=knowledge_client,
        evaluation_service=evaluation_service,
        evaluation_run_service=evaluation_run_service,
        quality_gate_service=quality_gate_service,
    )
    register_work_item_routes(app, ctx)
    register_workflow_routes(app, ctx)
