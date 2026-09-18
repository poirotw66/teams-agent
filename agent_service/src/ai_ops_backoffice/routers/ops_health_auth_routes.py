"""Ops health and auth config read routes."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Response

from ..auth import header_auth_allowed
from ..knowledge_bridge.capabilities import knowledge_capabilities_for


def register_ops_health_auth_routes(
    app: FastAPI,
    *,
    resolved_settings: Any,
    current_actor: Callable[..., Any],
) -> None:
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/auth/config")
    async def auth_config() -> dict[str, object]:
        entra_scopes_raw = (
            getattr(resolved_settings, "entra_scopes", None)
            or os.environ.get("AI_OPS_ENTRA_SCOPES")
            or ""
        )
        entra_scopes = [
            part.strip()
            for part in str(entra_scopes_raw).split(",")
            if part.strip()
        ]
        return {
            "authMode": resolved_settings.auth_mode,
            "headerAuthAllowed": (
                resolved_settings.auth_mode != "ENTRA" and header_auth_allowed()
            ),
            "entraTenantId": resolved_settings.entra_tenant_id,
            "entraClientId": resolved_settings.entra_client_id,
            "entraScopes": entra_scopes or None,
            "loginRedirectUri": "/console-v2/login",
        }

    @app.get("/api/capabilities")
    async def capabilities(actor: Any = Depends(current_actor)) -> dict[str, object]:
        from operations_core.access import CAPABILITIES

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
