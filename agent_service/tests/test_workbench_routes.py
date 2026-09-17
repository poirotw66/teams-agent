"""Test suite for workbench real API routes."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pdf_test_helpers import build_text_pdf_bytes

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.settings import PortalSettings


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    delegation_secret = "test-delegation-secret-at-least-32-characters"
    portal_settings = PortalSettings.from_env()
    portal_settings = PortalSettings(
        **{
            **portal_settings.__dict__,
            "service_token": "",
            "repository_mode": "MEMORY",
            "delegation_secret": delegation_secret,
            "require_service_token_with_delegation": False,
            "data_dir": tmp_path,
            "state_path": tmp_path / "portal-state.json",
            "drafts_dir": tmp_path / "drafts",
            "original_assets_dir": tmp_path / "originals",
            "deployment_environment": "test",
            "gemini_file_search_sync_enabled": False,
            "require_file_search_parity": False,
        }
    )
    portal_app = create_portal_app(portal_settings)
    settings = BackofficeSettings.from_env()
    settings = BackofficeSettings(
        **{
            **settings.__dict__,
            "knowledge_internal_url": "http://knowledge-portal",
            "knowledge_delegation_secret": delegation_secret,
            "knowledge_bridge_enabled": True,
            "knowledge_service_token": "",
        }
    )
    app = create_app(
        settings,
        knowledge_transport=httpx.ASGITransport(app=portal_app),
    )
    return TestClient(app)


def test_workbench_overview(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    res = client.get("/api/console/workbench/overview", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "kpis" in data
    assert "total_conversations" in data["kpis"]
    assert data["kpis"]["total_conversations"] >= 1
    assert "topTopics" in data
    assert len(data["topTopics"]) >= 1
    assert "blindSpots" in data


def test_workbench_conversations(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    res = client.get("/api/console/workbench/conversations", headers=headers)
    assert res.status_code == 200
    convs = res.json()
    assert isinstance(convs, list)
    assert len(convs) >= 1
    first = convs[0]
    assert "id" in first
    assert "messages" in first
    assert "status" in first


def test_workbench_faqs(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    res = client.get("/api/console/workbench/faqs", headers=headers)
    assert res.status_code == 200
    faqs = res.json()
    assert isinstance(faqs, list)
    assert len(faqs) >= 1
    assert any("VPN" in f.get("category", "") or "VPN" in str(f.get("questions", [])) for f in faqs)


def test_workbench_documents(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    res = client.get("/api/console/workbench/documents", headers=headers)
    assert res.status_code == 200
    docs = res.json()
    assert isinstance(docs, list)
    assert len(docs) >= 1
    first = docs[0]
    assert "title" in first
    assert "chunks" in first


def test_workbench_tickets(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    res = client.get("/api/console/workbench/tickets", headers=headers)
    assert res.status_code == 200
    tickets = res.json()
    assert isinstance(tickets, list)

    post_res = client.post(
        "/api/console/workbench/tickets",
        json={
            "title": "測試報修工單",
            "reporterName": "測試同仁",
            "reporterDept": "資訊處",
            "category": "HARDWARE",
            "assignedTeam": "現場硬體組",
        },
        headers=headers,
    )
    assert post_res.status_code == 200
    created = post_res.json()
    assert "ticket_number" in created


def test_workbench_simulation(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    res = client.post(
        "/api/console/workbench/simulate",
        json={"query": "VPN 連線失敗怎麼辦？"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    assert data["score"] > 50


def test_workbench_document_upload(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    res = client.post(
        "/api/console/workbench/documents/upload",
        data={
            "title": "2026 員工 IT 支援服務手冊測試版",
            "category": "辦公系統",
            "version": "v2.0",
            "deprecateOlderVersion": "true",
        },
        files={
            "file": (
                "員工 IT 支援服務手冊.pdf",
                build_text_pdf_bytes("Employee IT support guide"),
                "application/pdf",
            )
        },
        headers=headers,
    )

    assert res.status_code == 202
    data = res.json()
    assert data["title"] == "2026 員工 IT 支援服務手冊測試版"
    assert data["status"] == "PARSING"
    assert data["chunk_count"] == 0
    assert data["job_id"].startswith("pdfjob-")


def test_workbench_document_delete(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    # 1. Upload a markdown document
    md_content = b"# Test Delete Doc\n\n## Section 1\nThis is content to be deleted.\n"
    res = client.post(
        "/api/console/workbench/documents/upload",
        data={
            "title": "手冊刪除驗證文件",
            "category": "辦公系統",
            "version": "v1.0",
            "deprecateOlderVersion": "false",
        },
        files={"file": ("test_delete.md", md_content, "text/markdown")},
        headers=headers,
    )
    assert res.status_code == 202
    doc_id = res.json()["id"]

    # 2. Verify it is returned in document list
    docs = client.get("/api/knowledge/documents", headers=headers).json()
    assert any(d["document_id"] == doc_id for d in docs["items"])

    # 3. Delete document
    del_res = client.delete(f"/api/console/workbench/documents/{doc_id}", headers=headers)
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["ok"] is True
    assert del_data["deleted_document_id"] == doc_id

    # 4. Verify it is no longer in document list
    updated_docs = client.get("/api/knowledge/documents", headers=headers).json()
    assert not any(d["document_id"] == doc_id for d in updated_docs["items"])

    # 5. Non-existent document returns 404
    not_found_res = client.delete(
        "/api/console/workbench/documents/doc-non-existent-xyz", headers=headers
    )
    assert not_found_res.status_code == 404


def test_workbench_faq_delete(client: TestClient) -> None:
    headers = {
        "X-Backoffice-User-Id": "test-admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    # 1. Create temporary FAQ
    create_res = client.post(
        "/api/console/workbench/faqs",
        json={
            "question": "如何申請臨時門禁卡？",
            "answer": "請洽 1F 警衛室填寫換證登記簿。",
            "category": "總務行政",
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    faq_id = create_res.json()["id"]

    # 2. Delete the FAQ
    del_res = client.delete(f"/api/console/workbench/faqs/{faq_id}", headers=headers)
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["ok"] is True
    assert del_data["deleted_faq_id"] == faq_id

    # 3. Non-existent FAQ returns 404
    not_found_res = client.delete(
        "/api/console/workbench/faqs/faq-non-existent-xyz", headers=headers
    )
    assert not_found_res.status_code == 404
