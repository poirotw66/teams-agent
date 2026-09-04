"""Tests for Quality Case -> Knowledge Portal document draft vertical slice."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from test_ai_ops_backoffice import _seed_sample_events
from test_knowledge_portal import portal_headers, sample_document_payload

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.settings import PortalSettings

SECRET = "test-vertical-slice-secret"


def _backoffice_settings(tmp_path: Path) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    asyncio.run(_seed_sample_events(store_path, data_dir))
    return BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="FILE",
        ops_store_path=store_path,
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="FILE",
        knowledge_portal_url="http://knowledge-portal.test",
        knowledge_internal_url="http://knowledge-portal.test",
        knowledge_service_token="",
        knowledge_delegation_secret=SECRET,
        knowledge_bridge_enabled=True,
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


def test_quality_case_document_draft_creation_and_linking(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    transport = httpx.ASGITransport(app=portal_app)

    bo_settings = _backoffice_settings(tmp_path)
    bo_app = create_app(bo_settings, knowledge_transport=transport)
    client = TestClient(bo_app)

    # 1. Seed a quality case via candidate refresh/merge
    writer = headers("KNOWLEDGE_ADMIN")
    refreshed = client.post("/api/quality-candidates/refresh", headers=writer, json={"days": 30}).json()
    candidate = next(item for item in refreshed["items"] if item["issue_type_id"])
    quality_case = client.post(
        "/api/quality-candidates/merge",
        headers=writer,
        json={
            "candidate_ids": [candidate["candidate_id"]],
            "title": "改善 VPN 連線故障知識",
            "description": "提供使用者完整的 VPN 重設網路設定與重啟服務指引。",
            "priority": "HIGH",
        },
    ).json()["case"]

    case_id = quality_case["case_id"]
    initial_etag = quality_case["etag"]

    # 2. Call POST /api/quality-cases/{case_id}/document-draft
    draft_res = client.post(
        f"/api/quality-cases/{case_id}/document-draft",
        headers=writer,
        json={
            "expected_case_etag": initial_etag,
            "title": "VPN 連線異常排查手冊",
            "summary": "由品質案件自動產生之 VPN 連線疑難排解草稿",
            "markdown_content": "# VPN 排查步驟\n\n1. 檢查憑證\n2. 重新連線",
        },
    )
    assert draft_res.status_code == 200
    data = draft_res.json()
    assert data["partialSuccess"] is False
    doc = data["document"]
    doc_id = doc["document_id"]
    assert doc_id.startswith("doc-")
    assert doc["title"] == "VPN 連線異常排查手冊"
    assert doc["owner_unit_id"] == "IT Service Desk"

    # Case should now have the document linked
    updated_case = data["case"]
    assert doc_id in updated_case["document_ids"]

    # 3. Verify that the document can be read via /api/knowledge/documents/{doc_id}
    portal_get = client.get(f"/api/knowledge/documents/{doc_id}", headers=writer)
    assert portal_get.status_code == 200
    assert portal_get.json()["document"]["document_id"] == doc_id


def test_quality_case_document_draft_partial_success_handling(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    transport = httpx.ASGITransport(app=portal_app)

    bo_settings = _backoffice_settings(tmp_path)
    bo_app = create_app(bo_settings, knowledge_transport=transport)
    client = TestClient(bo_app)

    writer = headers("KNOWLEDGE_ADMIN")
    refreshed = client.post("/api/quality-candidates/refresh", headers=writer, json={"days": 30}).json()
    candidate = next(item for item in refreshed["items"] if item["issue_type_id"])
    quality_case = client.post(
        "/api/quality-candidates/merge",
        headers=writer,
        json={
            "candidate_ids": [candidate["candidate_id"]],
            "title": "改善 VPN 連線故障知識 2",
            "description": "測試衝突時的部分成功處理",
            "priority": "HIGH",
        },
    ).json()["case"]

    case_id = quality_case["case_id"]

    # Supply an invalid etag -> document gets created, but link_content raises FaqVersionConflictError
    draft_res = client.post(
        f"/api/quality-cases/{case_id}/document-draft",
        headers=writer,
        json={
            "expected_case_etag": 9999,
            "title": "部分成功文件",
            "summary": "此文件建立後關聯應回報 partialSuccess",
        },
    )
    assert draft_res.status_code == 200
    data = draft_res.json()
    assert data["partialSuccess"] is True
    assert "linkError" in data
    doc_id = data["document"]["document_id"]
    assert doc_id.startswith("doc-")
    # Document exists in portal
    portal_get = client.get(f"/api/knowledge/documents/{doc_id}", headers=writer)
    assert portal_get.status_code == 200


def test_quality_case_document_draft_requires_knowledge_create_capability(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    transport = httpx.ASGITransport(app=portal_app)

    bo_settings = _backoffice_settings(tmp_path)
    bo_app = create_app(bo_settings, knowledge_transport=transport)
    client = TestClient(bo_app)

    analyst = headers("ANALYST")
    res = client.post(
        "/api/quality-cases/case-any/document-draft",
        headers=analyst,
        json={"expected_case_etag": 1, "title": "未授權建立"},
    )
    assert res.status_code == 403


def test_link_existing_document_from_portal_via_bridge(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    transport = httpx.ASGITransport(app=portal_app)

    # 1. Create a document directly in Knowledge Portal
    portal_client = TestClient(portal_app)
    seed_payload = {**sample_document_payload(), "title": "Portal Seed Document", "owner_unit_id": "IT Service Desk"}
    created = portal_client.post(
        "/api/documents",
        json=seed_payload,
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert created.status_code == 200
    doc_id = created.json()["document"]["document_id"]

    # 2. Create quality case in Backoffice
    bo_settings = _backoffice_settings(tmp_path)
    bo_app = create_app(bo_settings, knowledge_transport=transport)
    client = TestClient(bo_app)

    writer = headers("KNOWLEDGE_ADMIN")
    refreshed = client.post("/api/quality-candidates/refresh", headers=writer, json={"days": 30}).json()
    candidate = next(item for item in refreshed["items"] if item["issue_type_id"])
    quality_case = client.post(
        "/api/quality-candidates/merge",
        headers=writer,
        json={
            "candidate_ids": [candidate["candidate_id"]],
            "title": "關聯既有 Portal 文件",
            "description": "測試 link_content 透過 bridge 驗證 Portal 內部文件",
            "priority": "HIGH",
        },
    ).json()["case"]

    case_id = quality_case["case_id"]

    # 3. Link the portal document to the quality case
    link_res = client.post(
        f"/api/quality-cases/{case_id}/content",
        headers=writer,
        json={
            "expected_etag": quality_case["etag"],
            "document_id": doc_id,
        },
    )
    assert link_res.status_code == 200
    linked_case = link_res.json()["case"]
    assert doc_id in linked_case["document_ids"]


def test_link_existing_document_cross_unit_rejected(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    transport = httpx.ASGITransport(app=portal_app)

    # Create document belonging to HR Operations
    portal_client = TestClient(portal_app)
    hr_payload = {**sample_document_payload(), "title": "HR Guide", "owner_unit_id": "HR Operations"}
    created = portal_client.post(
        "/api/documents",
        json=hr_payload,
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert created.status_code == 200
    doc_id = created.json()["document"]["document_id"]

    # Case belongs to IT Service Desk
    bo_settings = _backoffice_settings(tmp_path)
    bo_app = create_app(bo_settings, knowledge_transport=transport)
    client = TestClient(bo_app)

    writer = headers("KNOWLEDGE_ADMIN")
    refreshed = client.post("/api/quality-candidates/refresh", headers=writer, json={"days": 30}).json()
    candidate = next(item for item in refreshed["items"] if item["issue_type_id"])
    quality_case = client.post(
        "/api/quality-candidates/merge",
        headers=writer,
        json={
            "candidate_ids": [candidate["candidate_id"]],
            "title": "跨單位文件關聯防禦",
            "description": "不可關聯非同單位文件",
            "priority": "MEDIUM",
        },
    ).json()["case"]

    case_id = quality_case["case_id"]

    link_res = client.post(
        f"/api/quality-cases/{case_id}/content",
        headers=writer,
        json={
            "expected_etag": quality_case["etag"],
            "document_id": doc_id,
        },
    )
    assert link_res.status_code == 422
    assert "owner unit" in link_res.json().get("detail", "").lower()
