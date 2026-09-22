"""Ops health and auth config read routes."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from operations_core.audit import build_audit_event

from ..auth import header_auth_allowed
from ..knowledge_bridge.capabilities import knowledge_capabilities_for
from ..knowledge_bridge.formal_write_gate import (
    apply_knowledge_workspace_mode,
    can_switch_knowledge_workspace,
    clear_knowledge_workspace_mode,
    evaluate_knowledge_workspace_gate,
    filter_knowledge_capabilities_for_workspace,
)

logger = logging.getLogger(__name__)


class KnowledgeWorkspaceUpdateRequest(BaseModel):
    knowledgeWorkspaceMode: str = Field(min_length=1)
    reason: str | None = None


def _workspace_public_payload(
    settings: Any,
    *,
    actor: Any | None = None,
) -> dict[str, object]:
    gate = evaluate_knowledge_workspace_gate(settings)
    payload = gate.to_public_dict()
    payload["knowledgeWorkspaceSwitchAllowed"] = (
        can_switch_knowledge_workspace(actor) if actor is not None else False
    )
    payload["authMode"] = getattr(settings, "auth_mode", None)
    payload["relaxedWorkflow"] = bool(getattr(settings, "relaxed_workflow", False))
    return payload


def register_ops_health_auth_routes(
    app: FastAPI,
    *,
    resolved_settings: Any,
    current_actor: Callable[..., Any],
    query_service: Any | None = None,
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

        knowledge_caps = sorted(
            filter_knowledge_capabilities_for_workspace(
                knowledge_capabilities_for(actor),
                resolved_settings,
            )
        )
        workspace_payload = _workspace_public_payload(resolved_settings, actor=actor)
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
            "knowledgeUiUrl": "/console-v2/knowledge",
            "authMode": resolved_settings.auth_mode,
            "deploymentTenantId": resolved_settings.deployment_tenant_id,
            "relaxedWorkflow": resolved_settings.relaxed_workflow,
            "minTestCasesForReview": resolved_settings.min_test_cases_for_review,
            **workspace_payload,
        }

    @app.get("/api/knowledge-workspace")
    async def get_knowledge_workspace(
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        return _workspace_public_payload(resolved_settings, actor=actor)

    @app.put("/api/knowledge-workspace")
    async def put_knowledge_workspace(
        request: KnowledgeWorkspaceUpdateRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        if not can_switch_knowledge_workspace(actor):
            raise HTTPException(
                status_code=403,
                detail="需要 SYSTEM_ADMIN 或 KNOWLEDGE_ADMIN 才能切換知識工作區。",
            )
        before = evaluate_knowledge_workspace_gate(resolved_settings).workspace_mode
        try:
            mode = apply_knowledge_workspace_mode(
                resolved_settings,
                request.knowledgeWorkspaceMode,
                persist=True,
                actor_id=str(getattr(actor, "user_id", "") or "") or None,
                reason=request.reason,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except OSError as error:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to persist knowledge workspace mode: {error}",
            ) from error

        gate = evaluate_knowledge_workspace_gate(resolved_settings)
        logger.info(
            "knowledge_workspace_switched actor=%s role=%s before=%s after=%s "
            "formal_writes_allowed=%s reasons=%s source=%s",
            actor.user_id,
            actor.role,
            before,
            mode,
            gate.cloud_formal_writes_allowed,
            list(gate.block_reasons),
            gate.mode_source,
        )
        if query_service is not None:
            try:
                await query_service.audit_store.append(
                    build_audit_event(
                        actor_id=actor.user_id,
                        actor_role=actor.role,
                        action="knowledge.workspace.switch",
                        target_type="knowledge_workspace",
                        target_id=mode,
                        before={"knowledgeWorkspaceMode": before},
                        after={
                            "knowledgeWorkspaceMode": mode,
                            "cloudFormalWritesAllowed": gate.cloud_formal_writes_allowed,
                            "blockReasons": list(gate.block_reasons),
                            "knowledgeWorkspaceModeSource": gate.mode_source,
                            "knowledgeWorkspaceOverrideActive": gate.override_active,
                        },
                        reason=request.reason,
                        environment=str(
                            getattr(resolved_settings, "deployment_tenant_id", "dev")
                            or "dev"
                        ),
                    )
                )
            except Exception:  # noqa: BLE001 - audit must not block switch
                logger.exception("Failed to append knowledge workspace switch audit")

        return _workspace_public_payload(resolved_settings, actor=actor)

    @app.delete("/api/knowledge-workspace")
    async def delete_knowledge_workspace(
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        if not can_switch_knowledge_workspace(actor):
            raise HTTPException(
                status_code=403,
                detail="需要 SYSTEM_ADMIN 或 KNOWLEDGE_ADMIN 才能重設知識工作區。",
            )
        before = evaluate_knowledge_workspace_gate(resolved_settings).workspace_mode
        try:
            mode = clear_knowledge_workspace_mode(resolved_settings, persist=True)
        except OSError as error:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to clear knowledge workspace override: {error}",
            ) from error
        gate = evaluate_knowledge_workspace_gate(resolved_settings)
        logger.info(
            "knowledge_workspace_reset actor=%s role=%s before=%s after=%s source=%s",
            actor.user_id,
            actor.role,
            before,
            mode,
            gate.mode_source,
        )
        if query_service is not None:
            try:
                await query_service.audit_store.append(
                    build_audit_event(
                        actor_id=actor.user_id,
                        actor_role=actor.role,
                        action="knowledge.workspace.reset",
                        target_type="knowledge_workspace",
                        target_id=mode,
                        before={"knowledgeWorkspaceMode": before},
                        after={
                            "knowledgeWorkspaceMode": mode,
                            "knowledgeWorkspaceModeSource": gate.mode_source,
                            "knowledgeWorkspaceOverrideActive": gate.override_active,
                        },
                        reason="reset to env default",
                        environment=str(
                            getattr(resolved_settings, "deployment_tenant_id", "dev")
                            or "dev"
                        ),
                    )
                )
            except Exception:  # noqa: BLE001 - audit must not block reset
                logger.exception("Failed to append knowledge workspace reset audit")

        return _workspace_public_payload(resolved_settings, actor=actor)
