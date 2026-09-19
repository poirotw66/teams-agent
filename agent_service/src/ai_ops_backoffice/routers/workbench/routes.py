"""Register all workbench API routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from ai_ops_backoffice.adapters.workbench_json_store import resolve_project_root
from ai_ops_backoffice.adapters.workbench_repository import WorkbenchRepository

from .context import WorkbenchRouteContext
from .conversations import register_conversation_routes
from .documents import register_document_routes
from .faqs import register_faq_routes
from .overview import register_overview_routes
from .portal_response_models import PortalWorkbenchDtoCatalog
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
    repository = WorkbenchRepository(data_dir=project_root / "data")

    ctx = WorkbenchRouteContext(
        repository=repository,
        query_service=query_service,
        knowledge_client=knowledge_client,
        current_actor=current_actor,
        require_capability=require_capability,
    )

    @app.get(
        "/api/console/workbench/.well-known/portal-dto-catalog",
        response_model=PortalWorkbenchDtoCatalog,
        include_in_schema=True,
    )
    async def portal_dto_catalog() -> PortalWorkbenchDtoCatalog:
        """Schema catalog for OpenAPI codegen; not a product runtime surface."""
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="schema catalog only")

    register_overview_routes(app, ctx)
    register_conversation_routes(app, ctx)
    register_faq_routes(app, ctx)
    register_document_routes(app, ctx)
    register_ticket_routes(app, ctx)
    register_simulation_routes(app, ctx)
