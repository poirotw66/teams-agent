from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, Response

from ..auth import header_auth_allowed
from ..knowledge_bridge.capabilities import knowledge_capabilities_for
from .analytics_router import (
    ALLOWED_EXPORT_FORMATS,
    EXPORT_CAPABILITIES,
    register_analytics_routes,
)
from .conversations_router import register_conversations_routes
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

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/auth/config")
    async def auth_config() -> dict[str, object]:
        return {
            "authMode": resolved_settings.auth_mode,
            "headerAuthAllowed": (
                resolved_settings.auth_mode != "ENTRA" and header_auth_allowed()
            ),
        }

    @app.get("/api/capabilities")
    async def capabilities(actor: Any = Depends(current_actor)) -> dict[str, object]:
        from agent_service.operations.access import CAPABILITIES

        knowledge_caps = sorted(knowledge_capabilities_for(actor))
        return {
            "userId": actor.user_id,
            "userName": actor.display_name or actor.user_id,
            "displayName": actor.display_name or actor.user_id,
            "role": actor.role,
            "capabilities": sorted(CAPABILITIES.get(actor.role, frozenset())),
            "knowledgeCapabilities": knowledge_caps,
            "ownerUnitIds": list(actor.owner_unit_ids),
            "knowledgePortalUrl": resolved_settings.knowledge_portal_url,
            "knowledgeBridgeEnabled": bool(
                resolved_settings.knowledge_bridge_enabled
                and resolved_settings.knowledge_delegation_secret
            ),
            "knowledgeUiUrl": "/knowledge-ui/#/knowledge",
            "authMode": resolved_settings.auth_mode,
            "deploymentTenantId": resolved_settings.deployment_tenant_id,
            "relaxedWorkflow": resolved_settings.relaxed_workflow,
            "minTestCasesForReview": resolved_settings.min_test_cases_for_review,
        }

    # Delegate to sub-routers
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
