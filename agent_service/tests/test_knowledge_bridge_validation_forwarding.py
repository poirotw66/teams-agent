"""Tests for BFF proxy upstream error handling and validation issues forwarding."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from test_knowledge_portal import portal_headers, sample_document_payload

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.auth import resolve_actor
from ai_ops_backoffice.knowledge_bridge.client import KnowledgePortalClient
from ai_ops_backoffice.knowledge_bridge.errors import KnowledgeBridgeError
from ai_ops_backoffice.knowledge_bridge.routes import _safe_upstream_error, build_knowledge_router
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.settings import PortalSettings

SECRET = "test-delegation-secret-validation"


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


def test_safe_upstream_error_dict_validation_summary() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "detail": {
            "code": "VALIDATION_FAILED",
            "message": "內容檢查未通過，請修正標示的問題後再試。",
            "issues": [
                {
                    "code": "MISSING_FIELD",
                    "severity": "BLOCKING",
                    "message": "正文不可為空",
                    "field": "markdown_content",
                }
            ],
        }
    }
    result = _safe_upstream_error(mock_resp, correlation_id="corr-123", status=422)
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert result["error"]["message"] == "內容檢查未通過，請修正標示的問題後再試。"
    assert result["error"]["correlationId"] == "corr-123"
    assert result["error"]["retryable"] is False
    assert len(result["error"]["details"]["issues"]) == 1
    assert result["error"]["details"]["issues"][0]["field"] == "markdown_content"
    assert result["error"]["details"]["issues"][0]["message"] == "正文不可為空"


def test_safe_upstream_error_fastapi_validation_list() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "detail": [
            {"loc": ["body", "title"], "msg": "field required", "type": "value_error.missing"}
        ]
    }
    result = _safe_upstream_error(mock_resp, correlation_id="corr-456", status=422)
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert result["error"]["message"] == "內容檢查或參數驗證未通過。"
    assert len(result["error"]["details"]["issues"]) == 1
    assert result["error"]["details"]["issues"][0]["loc"] == ["body", "title"]


def test_safe_upstream_error_conflict_and_forbidden() -> None:
    mock_409 = MagicMock()
    mock_409.json.return_value = {"detail": {"code": "CONFLICT", "message": "Version mismatch"}}
    res_409 = _safe_upstream_error(mock_409, correlation_id="c-409", status=409)
    assert res_409["error"]["code"] == "KNOWLEDGE_VERSION_CONFLICT"
    assert res_409["error"]["message"] == "Version mismatch"

    mock_403 = MagicMock()
    mock_403.json.return_value = {"detail": "Forbidden access"}
    res_403 = _safe_upstream_error(mock_403, correlation_id="c-403", status=403)
    assert res_403["error"]["code"] == "KNOWLEDGE_UPSTREAM_FORBIDDEN"
    assert res_403["error"]["message"] == "Forbidden access"


def test_bff_proxy_forwards_validation_issues_end_to_end(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    portal_client = TestClient(portal_app)

    # 1. Create a document directly in portal
    resp = portal_client.post(
        "/api/documents",
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
        json=sample_document_payload(),
    )
    assert resp.status_code == 200
    doc_id = resp.json()["document"]["document_id"]
    etag = resp.json()["document"]["etag"]

    # 2. Set up BFF mini app
    transport = httpx.ASGITransport(app=portal_app)
    bridge_client = KnowledgePortalClient(
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
        x_backoffice_role: str | None = Header(default="KNOWLEDGE_ADMIN", alias="X-Backoffice-Role"),
        x_backoffice_owner_units: str | None = Header(default="", alias="X-Backoffice-Owner-Units"),
        x_backoffice_tenant_id: str | None = Header(default=None, alias="X-Backoffice-Tenant-Id"),
    ) -> ActorContext:
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

    @mini.exception_handler(KnowledgeBridgeError)
    async def _kb(_req, exc: KnowledgeBridgeError):
        return JSONResponse(status_code=exc.status_code, content=exc.as_response())

    mini.include_router(
        build_knowledge_router(client=bridge_client, current_actor=current_actor, enabled=True),
        prefix="/api/knowledge",
    )
    bff_api = TestClient(mini)

    # 3. Update draft with empty markdown content (which triggers ValidationSummary BLOCKING issue)
    invalid_draft_payload = {
        "etag": etag,
        "title": "Updated Title",
        "summary": "Valid summary",
        "category": "IT",
        "owner_unit_id": "IT Service Desk",
        "business_contact": "it@test.com",
        "audience_type": "ALL_EMPLOYEES",
        "audience_group_ids": [],
        "markdown_content": "   ",  # Blank content triggers validation issue!
    }

    bff_resp = bff_api.put(
        f"/api/knowledge/documents/{doc_id}/draft",
        headers={
            "X-Backoffice-User-Id": "admin1",
            "X-Backoffice-User-Name": "Admin",
            "X-Backoffice-Role": "KNOWLEDGE_ADMIN",
            "X-Backoffice-Owner-Units": "IT Service Desk",
        },
        json=invalid_draft_payload,
    )

    assert bff_resp.status_code == 422
    body = bff_resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert "內容檢查" in err["message"]
    assert "details" in err
    assert "issues" in err["details"]
    assert len(err["details"]["issues"]) > 0

    # 4. Now test submit-review when draft validation has blocking issues
    # Save draft with RESTRICTED_GROUPS but empty audience_group_ids (which triggers BLOCKING validation issue)
    valid_pydantic_draft = {
        "etag": etag,
        "title": "Valid Draft Title",
        "summary": "Valid summary",
        "category": "IT",
        "owner_unit_id": "IT Service Desk",
        "business_contact": "it@test.com",
        "audience_type": "RESTRICTED_GROUPS",
        "audience_group_ids": [],
        "effective_at": "2026-01-01",
        "review_due_at": "2026-12-31",
        "change_reason": "Testing validation",
        "markdown_content": "Valid markdown content for the draft.",
    }
    save_resp = bff_api.put(
        f"/api/knowledge/documents/{doc_id}/draft",
        headers={
            "X-Backoffice-User-Id": "admin1",
            "X-Backoffice-User-Name": "Admin",
            "X-Backoffice-Role": "KNOWLEDGE_ADMIN",
            "X-Backoffice-Owner-Units": "IT Service Desk",
        },
        json=valid_pydantic_draft,
    )
    assert save_resp.status_code == 200
    current_etag = save_resp.json()["document"]["etag"]

    submit_resp = bff_api.post(
        f"/api/knowledge/documents/{doc_id}/submit-review",
        headers={
            "X-Backoffice-User-Id": "admin1",
            "X-Backoffice-User-Name": "Admin",
            "X-Backoffice-Role": "KNOWLEDGE_ADMIN",
            "X-Backoffice-Owner-Units": "IT Service Desk",
        },
        json={"etag": current_etag, "change_reason": "Ready for review"},
    )
    assert submit_resp.status_code == 422
    submit_body = submit_resp.json()
    assert submit_body["error"]["code"] == "VALIDATION_FAILED"
    assert "內容檢查未通過" in submit_body["error"]["message"]
    assert len(submit_body["error"]["details"]["issues"]) > 0
    assert any(
        i.get("field") == "audience_group_ids" or i.get("code") == "AUDIENCE_GROUPS_REQUIRED"
        for i in submit_body["error"]["details"]["issues"]
    )
