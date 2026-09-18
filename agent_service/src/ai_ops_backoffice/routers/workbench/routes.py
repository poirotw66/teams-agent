"""Register all workbench API routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from ai_ops_backoffice.adapters.workbench_json_store import (
    WorkbenchJsonStore,
    resolve_project_root,
)

from .context import WorkbenchRouteContext
from .conversations import register_conversation_routes
from .documents import register_document_routes
from .faqs import register_faq_routes
from .overview import register_overview_routes
from .simulation import register_simulation_routes
from .tickets import register_ticket_routes


def register_workbench_routes(
    app: FastAPI,
    *,
    resolved_settings: Any,
    query_service: Any,
    knowledge_client: Any,
    current_actor: Callable[..., Any],
    require_capability: Callable[[Any, str], None],
) -> None:
    ops_store_path = resolved_settings.ops_store_path
    project_root = resolve_project_root(ops_store_path)
    data_dir = project_root / "data"
    store = WorkbenchJsonStore()

    ctx = WorkbenchRouteContext(
        data_dir=data_dir,
        faqs_file=data_dir / "ops" / "phase2" / "faqs.json",
        portal_state_file=data_dir / "portal_state" / "portal_state.json",
        chunks_file=data_dir / "index" / "chunks.json",
        tickets_file=data_dir / "ops" / "tickets.json",
        state_file=data_dir / "ops" / "workbench_state.json",
        query_service=query_service,
        knowledge_client=knowledge_client,
        current_actor=current_actor,
        require_capability=require_capability,
        store=store,
    )

    register_overview_routes(app, ctx)
    register_conversation_routes(app, ctx)
    register_faq_routes(app, ctx)
    register_document_routes(app, ctx)
    register_ticket_routes(app, ctx)
    register_simulation_routes(app, ctx)
