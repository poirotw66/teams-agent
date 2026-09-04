"""M1 knowledge bridge: adapter, delegation, and forged-header rejection."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_knowledge_portal import portal_headers, sample_document_payload

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.knowledge_bridge.capabilities import (
    has_knowledge_capability,
    portal_role_for,
)
from ai_ops_backoffice.knowledge_bridge.delegation import (
    issue_delegation_envelope,
    verify_delegation_envelope,
)
from ai_ops_backoffice.knowledge_bridge.errors import assert_allowlisted
from ai_ops_backoffice.settings import BackofficeSettings
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.settings import PortalSettings

SECRET = "test-delegation-secret-m1"


def _backoffice_settings(tmp_path: Path, *, bridge: bool = True) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    return BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="FILE",
        knowledge_portal_url="http://knowledge-portal.test",
        knowledge_internal_url="http://knowledge-portal.test",
        knowledge_service_token="",
        knowledge_delegation_secret=SECRET if bridge else "",
        knowledge_bridge_enabled=bridge,
        deployment_tenant_id="local-development",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        governance_store_path=tmp_path / "governance.json",
    )


def _portal_settings(tmp_path: Path) -> PortalSettings:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "data_dir", tmp_path)
    object.__setattr__(settings, "drafts_dir", tmp_path / "drafts")
    object.__setattr__(settings, "require_dual_approval", False)
    object.__setattr__(settings, "relaxed_workflow", True)
    object.__setattr__(settings, "embedding_model", None)
    object.__setattr__(settings, "delegation_secret", SECRET)
    object.__setattr__(settings, "require_service_token_with_delegation", False)
    return settings


def headers(role: str = "KNOWLEDGE_ADMIN") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_path_allowlist_blocks_admin_and_traversal() -> None:
    assert assert_allowlisted("documents") == "documents"
    with pytest.raises(Exception):
        assert_allowlisted("admin/bootstrap-release-0001")
    with pytest.raises(Exception):
        assert_allowlisted("../secrets")


def test_capability_mapping_is_not_role_name_alias() -> None:
    knowledge_admin = ActorContext(
        user_id="k1",
        display_name="K",
        role="KNOWLEDGE_ADMIN",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="t1",
    )
    analyst = ActorContext(
        user_id="a1",
        display_name="A",
        role="ANALYST",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="t1",
    )
    assert has_knowledge_capability(knowledge_admin, "knowledge.read")
    assert has_knowledge_capability(knowledge_admin, "knowledge.publish")
    assert not has_knowledge_capability(analyst, "knowledge.read")
    assert portal_role_for(knowledge_admin) in {"MANAGER", "PLATFORM"}


def test_delegation_roundtrip_and_tamper_rejected() -> None:
    actor = ActorContext(
        user_id="user-1",
        display_name="Editor",
        role="KNOWLEDGE_ADMIN",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="local-development",
    )
    token = issue_delegation_envelope(actor, secret=SECRET, correlation_id="corr-1")
    payload = verify_delegation_envelope(token, secret=SECRET)
    assert payload["sub"] == "user-1"
    assert payload["portalRole"] in {"MANAGER", "PLATFORM"}
    body, signature = token.split(".", 1)
    with pytest.raises(Exception):
        verify_delegation_envelope(f"{body}.deadbeef", secret=SECRET)


def test_knowledge_bridge_document_read_via_asgi(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    transport = httpx.ASGITransport(app=portal_app)
    # Seed a document directly on Portal with legacy headers (isolated local mode).
    portal_client = TestClient(portal_app)
    created = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert created.status_code == 200
    document_id = created.json()["document"]["document_id"]

    settings = _backoffice_settings(tmp_path, bridge=True)
    _ = create_app(settings)
    # Inject ASGI transport into the client created by create_app.
    from ai_ops_backoffice.knowledge_bridge.client import KnowledgePortalClient

    client = KnowledgePortalClient(
        base_url="http://knowledge-portal.test",
        service_token="",
        delegation_secret=SECRET,
        transport=transport,
    )
    # Rebuild router with transport-backed client.
    from ai_ops_backoffice.knowledge_bridge import build_knowledge_router

    # Access the same current_actor dependency by creating a dedicated app for the test.
    bo = TestClient(create_app(settings))
    # Monkeypatch: call client directly through status then replace via request path.
    # Simpler approach: use KnowledgePortalClient with transport in a fresh mini-app.
    from fastapi import FastAPI, Header, HTTPException

    from ai_ops_backoffice.auth import BackofficeAuthError, resolve_actor

    mini = FastAPI()

    def current_actor(
        authorization: str | None = Header(default=None),
        x_backoffice_user_id: str | None = Header(default=None, alias="X-Backoffice-User-Id"),
        x_backoffice_user_name: str | None = Header(default=None, alias="X-Backoffice-User-Name"),
        x_backoffice_role: str | None = Header(default="ANALYST", alias="X-Backoffice-Role"),
        x_backoffice_owner_units: str | None = Header(default="", alias="X-Backoffice-Owner-Units"),
        x_backoffice_tenant_id: str | None = Header(default=None, alias="X-Backoffice-Tenant-Id"),
    ):
        try:
            return resolve_actor(
                auth_mode="HEADER",
                authorization=authorization,
                header_user_id=x_backoffice_user_id,
                header_user_name=x_backoffice_user_name,
                header_role=x_backoffice_role,
                header_owner_units=x_backoffice_owner_units,
                header_tenant_id=x_backoffice_tenant_id,
                default_owner_unit_id="IT Service Desk",
                entra_tenant_id=None,
                entra_client_id=None,
            )
        except BackofficeAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    from fastapi.responses import JSONResponse

    from ai_ops_backoffice.knowledge_bridge.errors import KnowledgeBridgeError

    @mini.exception_handler(KnowledgeBridgeError)
    async def _kb(_req, exc: KnowledgeBridgeError):
        return JSONResponse(status_code=exc.status_code, content=exc.as_response())

    mini.include_router(
        build_knowledge_router(client=client, current_actor=current_actor, enabled=True),
        prefix="/api/knowledge",
    )
    api = TestClient(mini)

    denied = api.get(f"/api/knowledge/documents/{document_id}", headers=headers("ANALYST"))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "KNOWLEDGE_FORBIDDEN"

    forged = api.get(
        f"/api/knowledge/documents/{document_id}",
        headers={
            **headers("KNOWLEDGE_ADMIN"),
            "X-Portal-Role": "PLATFORM",
            "X-Portal-User-Id": "attacker",
        },
    )
    assert forged.status_code == 400
    assert forged.json()["error"]["code"] == "KNOWLEDGE_FORGED_PORTAL_IDENTITY"

    ok = api.get(
        f"/api/knowledge/documents/{document_id}",
        headers=headers("KNOWLEDGE_ADMIN"),
    )
    assert ok.status_code == 200
    assert ok.json()["document"]["document_id"] == document_id

    blocked = api.post(
        "/api/knowledge/admin/bootstrap-release-0001",
        headers=headers("SYSTEM_ADMIN"),
        json={},
    )
    assert blocked.status_code == 404

    _ = bo  # ensure create_app still constructs with new settings


def test_capabilities_advertise_knowledge_bridge(tmp_path: Path) -> None:
    client = TestClient(create_app(_backoffice_settings(tmp_path, bridge=True)))
    response = client.get("/api/capabilities", headers=headers("KNOWLEDGE_ADMIN"))
    assert response.status_code == 200
    body = response.json()
    assert body["knowledgeBridgeEnabled"] is True
    assert "knowledge.read" in body["knowledgeCapabilities"]
    assert body["knowledgeUiUrl"] == "/knowledge-ui/#/knowledge"


def test_knowledge_ui_same_origin_entry(tmp_path: Path) -> None:
    client = TestClient(create_app(_backoffice_settings(tmp_path, bridge=True)))
    page = client.get("/knowledge-ui/")
    assert page.status_code == 200
    assert b"__AI_OPS_KNOWLEDGE_EMBED__" in page.content
    assert b"/static/kp/" in page.content
    css = client.get("/static/kp/styles.css")
    assert css.status_code == 200
