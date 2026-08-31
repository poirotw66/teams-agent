from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowledge_portal.api import create_app
from knowledge_portal.settings import PortalSettings
from knowledge_portal.validation import validate_draft

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "knowledge_portal" / "static"


@pytest.fixture
def portal_client() -> TestClient:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    return TestClient(create_app(settings))


def portal_headers() -> dict[str, str]:
    return {
        "X-Portal-User-Id": "contributor.demo",
        "X-Portal-User-Name": "Contributor Demo",
        "X-Portal-Role": "CONTRIBUTOR",
        "X-Portal-Owner-Units": "IT Service Desk",
    }


def sample_document_payload() -> dict[str, str]:
    return {
        "title": "VPN 登入問題",
        "summary": "協助員工排除 VPN 登入失敗。",
        "category": "VPN",
        "owner_unit_id": "IT Service Desk",
        "business_contact": "it-helpdesk@example.test",
        "audience_type": "ALL_EMPLOYEES",
        "audience_group_ids": [],
        "effective_at": "2026-08-01",
        "review_due_at": "2026-12-01",
        "change_summary": "Initial draft",
        "change_reason": "建立新的 VPN 協助文件。",
        "markdown_content": "# VPN 登入問題\n\n請先確認帳號未鎖定。",
    }


def test_validation_messages_are_traditional_chinese() -> None:
    summary = validate_draft(
        title="",
        owner_unit_id="",
        change_reason="",
        effective_at="",
        review_due_at="",
        audience_type="ALL_EMPLOYEES",
        audience_group_ids=[],
        markdown_content="   ",
    )
    assert summary.has_blocking
    for issue in summary.issues:
        assert issue.message
        assert "required" not in issue.message.lower()
        assert "cannot" not in issue.message.lower()


def test_version_conflict_message_is_traditional_chinese(portal_client: TestClient) -> None:
    create = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(),
    )
    assert create.status_code == 200
    document_id = create.json()["document"]["document_id"]

    response = portal_client.put(
        f"/api/documents/{document_id}/draft",
        json={
            **sample_document_payload(),
            "etag": "stale-etag",
            "change_reason": "Update draft",
        },
        headers=portal_headers(),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["code"] == "CONFLICT"
    assert "重新載入" in body["detail"]["message"]


def test_index_html_exposes_portal_build(portal_client: TestClient) -> None:
    response = portal_client.get("/")
    assert response.status_code == 200
    assert 'name="portal-build" content="20260831d"' in response.text
    assert "/static/js/main.js?v=20260831d" in response.text


def test_static_portal_assets_disable_cache(portal_client: TestClient) -> None:
    response = portal_client.get("/static/js/ui.js")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache, no-store, must-revalidate"


def test_static_js_contains_ux_markers() -> None:
    content_js = (STATIC_DIR / "js/views/document-detail/tabs/content.js").read_text(encoding="utf-8")
    tests_js = (STATIC_DIR / "js/views/document-detail/tabs/tests.js").read_text(encoding="utf-8")
    releases_js = (STATIC_DIR / "js/views/releases.js").read_text(encoding="utf-8")
    errors_js = (STATIC_DIR / "js/errors.js").read_text(encoding="utf-8")

    assert "renderParsePreview" in content_js
    assert "引用來源" in tests_js
    assert "切換發布版本" in releases_js
    assert "版本衝突" in errors_js
