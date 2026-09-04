"""Tests for Item 2: Cross-unit isolation and highest administrator platform privileges."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from test_knowledge_portal import sample_document_payload

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.auth import BackofficeAuthError, resolve_actor
from ai_ops_backoffice.knowledge_bridge import build_knowledge_router
from ai_ops_backoffice.knowledge_bridge.capabilities import portal_role_for
from ai_ops_backoffice.knowledge_bridge.client import KnowledgePortalClient
from ai_ops_backoffice.knowledge_bridge.errors import KnowledgeBridgeError
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.models import PortalActor
from knowledge_portal.rbac import (
    PortalPermissionError,
    can_edit_document,
    can_view_document,
    ensure_document_visible,
)
from knowledge_portal.settings import PortalSettings

SECRET = "test-delegation-secret-isolation"


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

def _portal_headers(
    *,
    role: str = "CONTRIBUTOR",
    user_id: str = "contributor.demo",
    name: str = "Contributor Demo",
    owner_units: str = "IT Service Desk",
) -> dict[str, str]:
    return {
        "X-Portal-User-Id": user_id,
        "X-Portal-User-Name": name,
        "X-Portal-Role": role,
        "X-Portal-Owner-Units": owner_units,
    }


def test_role_mapping_highest_admin_vs_knowledge_admin() -> None:
    system_admin = ActorContext(
        user_id="sys1",
        display_name="System Admin",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(),
        tenant_id="tenant-1",
    )
    knowledge_admin = ActorContext(
        user_id="k1",
        display_name="Knowledge Admin",
        role="KNOWLEDGE_ADMIN",
        owner_unit_ids=("UNIT-A",),
        tenant_id="tenant-1",
    )
    auditor = ActorContext(
        user_id="aud1",
        display_name="Auditor",
        role="AUDITOR",
        owner_unit_ids=("UNIT-A",),
        tenant_id="tenant-1",
    )

    # Highest admin maps to PLATFORM
    assert portal_role_for(system_admin) == "PLATFORM"
    # Unit-scoped knowledge admin maps to MANAGER, never PLATFORM
    assert portal_role_for(knowledge_admin) == "MANAGER"
    assert portal_role_for(auditor) == "AUDITOR"


def test_rbac_unit_and_tenant_isolation_unit_checks() -> None:
    platform_actor = PortalActor(
        user_id="plat1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
        tenant_id="tenant-1",
    )
    manager_a = PortalActor(
        user_id="mgr_a",
        display_name="Manager A",
        role="MANAGER",
        owner_unit_ids=["UNIT-A"],
        tenant_id="tenant-1",
    )
    manager_b = PortalActor(
        user_id="mgr_b",
        display_name="Manager B",
        role="MANAGER",
        owner_unit_ids=["UNIT-B"],
        tenant_id="tenant-1",
    )

    # Platform (highest administrator) has all permissions across units
    assert can_view_document(platform_actor, owner_unit_id="UNIT-A", created_by="other")
    assert can_view_document(platform_actor, owner_unit_id="UNIT-B", created_by="other")
    assert can_edit_document(platform_actor, owner_unit_id="UNIT-A", created_by="other")
    assert can_edit_document(platform_actor, owner_unit_id="UNIT-B", created_by="other")

    # Manager A can view and edit in UNIT-A
    assert can_view_document(manager_a, owner_unit_id="UNIT-A", created_by="other")
    assert can_edit_document(manager_a, owner_unit_id="UNIT-A", created_by="other")

    # Manager A CANNOT view or edit in UNIT-B
    assert not can_view_document(manager_a, owner_unit_id="UNIT-B", created_by="other")
    assert not can_edit_document(manager_a, owner_unit_id="UNIT-B", created_by="other")

    # Manager B can view and edit in UNIT-B, but CANNOT in UNIT-A
    assert can_view_document(manager_b, owner_unit_id="UNIT-B", created_by="other")
    assert not can_view_document(manager_b, owner_unit_id="UNIT-A", created_by="other")

    with pytest.raises(PortalPermissionError):
        ensure_document_visible(manager_a, owner_unit_id="UNIT-B", created_by="other")


def test_portal_api_cross_unit_isolation_and_highest_admin(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    client = TestClient(portal_app)

    # 1. Seed document under UNIT-A by manager A
    payload_a = sample_document_payload()
    payload_a["owner_unit_id"] = "UNIT-A"
    payload_a["title"] = "Doc in Unit A"
    resp_a = client.post(
        "/api/documents",
        json=payload_a,
        headers=_portal_headers(user_id="mgr_a", name="Mgr A", role="MANAGER", owner_units="UNIT-A"),
    )
    assert resp_a.status_code == 200
    doc_a_id = resp_a.json()["document"]["document_id"]

    # 2. Seed document under UNIT-B by manager B
    payload_b = sample_document_payload()
    payload_b["owner_unit_id"] = "UNIT-B"
    payload_b["title"] = "Doc in Unit B"
    resp_b = client.post(
        "/api/documents",
        json=payload_b,
        headers=_portal_headers(user_id="mgr_b", name="Mgr B", role="MANAGER", owner_units="UNIT-B"),
    )
    assert resp_b.status_code == 200
    doc_b_id = resp_b.json()["document"]["document_id"]

    # 3. Manager A cannot read Doc B
    resp_read_b = client.get(
        f"/api/documents/{doc_b_id}",
        headers=_portal_headers(user_id="mgr_a", name="Mgr A", role="MANAGER", owner_units="UNIT-A"),
    )
    assert resp_read_b.status_code == 403

    # 4. Manager A cannot create a document in UNIT-B
    payload_cross = sample_document_payload()
    payload_cross["owner_unit_id"] = "UNIT-B"
    resp_cross = client.post(
        "/api/documents",
        json=payload_cross,
        headers=_portal_headers(user_id="mgr_a", name="Mgr A", role="MANAGER", owner_units="UNIT-A"),
    )
    assert resp_cross.status_code == 403

    # 5. Manager A listing documents only sees Doc A
    resp_list_a = client.get(
        "/api/documents",
        headers=_portal_headers(user_id="mgr_a", name="Mgr A", role="MANAGER", owner_units="UNIT-A"),
    )
    assert resp_list_a.status_code == 200
    listed_ids_a = {d["document_id"] for d in resp_list_a.json()["items"]}
    assert doc_a_id in listed_ids_a
    assert doc_b_id not in listed_ids_a

    # 6. Highest Admin (PLATFORM) can read both Doc A and Doc B, and sees both in list
    resp_plat_a = client.get(
        f"/api/documents/{doc_a_id}",
        headers=_portal_headers(user_id="plat", name="Platform Admin", role="PLATFORM"),
    )
    assert resp_plat_a.status_code == 200

    resp_plat_b = client.get(
        f"/api/documents/{doc_b_id}",
        headers=_portal_headers(user_id="plat", name="Platform Admin", role="PLATFORM"),
    )
    assert resp_plat_b.status_code == 200

    resp_list_plat = client.get(
        "/api/documents",
        headers=_portal_headers(user_id="plat", name="Platform Admin", role="PLATFORM"),
    )
    assert resp_list_plat.status_code == 200
    listed_ids_plat = {d["document_id"] for d in resp_list_plat.json()["items"]}
    assert doc_a_id in listed_ids_plat
    assert doc_b_id in listed_ids_plat


def test_knowledge_bridge_delegation_cross_unit_enforcement(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    transport = httpx.ASGITransport(app=portal_app)
    portal_client = TestClient(portal_app)

    # Seed Doc A under UNIT-A
    payload_a = sample_document_payload()
    payload_a["owner_unit_id"] = "UNIT-A"
    created_a = portal_client.post(
        "/api/documents",
        json=payload_a,
        headers=_portal_headers(user_id="creator", name="Creator", role="PLATFORM"),
    )
    doc_a_id = created_a.json()["document"]["document_id"]

    # Seed Doc B under UNIT-B
    payload_b = sample_document_payload()
    payload_b["owner_unit_id"] = "UNIT-B"
    created_b = portal_client.post(
        "/api/documents",
        json=payload_b,
        headers=_portal_headers(user_id="creator", name="Creator", role="PLATFORM"),
    )
    doc_b_id = created_b.json()["document"]["document_id"]

    # Wire up Backoffice BFF router
    client = KnowledgePortalClient(
        base_url="http://knowledge-portal.test",
        service_token="",
        delegation_secret=SECRET,
        transport=transport,
    )

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

    @mini.exception_handler(KnowledgeBridgeError)
    async def _kb(_req, exc: KnowledgeBridgeError):
        return JSONResponse(status_code=exc.status_code, content=exc.as_response())

    mini.include_router(
        build_knowledge_router(client=client, current_actor=current_actor, enabled=True),
        prefix="/api/knowledge",
    )
    api = TestClient(mini)

    # 1. Backoffice KNOWLEDGE_ADMIN of UNIT-A requests Doc A via Knowledge Bridge -> 200 OK
    resp_a = api.get(
        f"/api/knowledge/documents/{doc_a_id}",
        headers={
            "X-Backoffice-User-Id": "user-kadmin-a",
            "X-Backoffice-User-Name": "Knowledge Admin A",
            "X-Backoffice-Role": "KNOWLEDGE_ADMIN",
            "X-Backoffice-Owner-Units": "UNIT-A",
        },
    )
    assert resp_a.status_code == 200
    assert resp_a.json()["document"]["document_id"] == doc_a_id

    # 2. Backoffice KNOWLEDGE_ADMIN of UNIT-A requests Doc B (OTHER-UNIT) via Knowledge Bridge -> 403 Forbidden!
    resp_b = api.get(
        f"/api/knowledge/documents/{doc_b_id}",
        headers={
            "X-Backoffice-User-Id": "user-kadmin-a",
            "X-Backoffice-User-Name": "Knowledge Admin A",
            "X-Backoffice-Role": "KNOWLEDGE_ADMIN",
            "X-Backoffice-Owner-Units": "UNIT-A",
        },
    )
    assert resp_b.status_code == 403
    assert resp_b.json()["error"]["code"] == "KNOWLEDGE_UPSTREAM_FORBIDDEN"

    # 3. Backoffice SYSTEM_ADMIN (highest administrator) requests Doc A and Doc B -> both 200 OK
    resp_sys_a = api.get(
        f"/api/knowledge/documents/{doc_a_id}",
        headers={
            "X-Backoffice-User-Id": "user-sysadmin",
            "X-Backoffice-User-Name": "System Admin",
            "X-Backoffice-Role": "SYSTEM_ADMIN",
            "X-Backoffice-Owner-Units": "",
        },
    )
    assert resp_sys_a.status_code == 200

    resp_sys_b = api.get(
        f"/api/knowledge/documents/{doc_b_id}",
        headers={
            "X-Backoffice-User-Id": "user-sysadmin",
            "X-Backoffice-User-Name": "System Admin",
            "X-Backoffice-Role": "SYSTEM_ADMIN",
            "X-Backoffice-Owner-Units": "",
        },
    )
    assert resp_sys_b.status_code == 200
