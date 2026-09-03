"""Cross-service governance integration for Phase 1 §12.7."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from test_ai_ops_backoffice import _seed_sample_events, headers
from test_knowledge_portal import portal_headers, sample_document_payload
from pdf_test_helpers import build_text_pdf_bytes

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.settings import PortalSettings


def _portal_settings(tmp_path: Path) -> PortalSettings:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "data_dir", tmp_path)
    object.__setattr__(settings, "require_dual_approval", False)
    object.__setattr__(settings, "relaxed_workflow", True)
    object.__setattr__(settings, "embedding_model", None)
    return settings


def _publish_markdown_document(portal_client: TestClient) -> str:
    create = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert create.status_code == 200
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]

    submit = portal_client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready for review"},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert submit.status_code == 200
    review_id = submit.json()["open_review"]["review_id"]

    approve = portal_client.post(
        f"/api/reviews/{review_id}/decision",
        json={"decision": "APPROVED", "comment": "ok", "policy_exceptions": []},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert approve.status_code == 200

    detail = portal_client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER"),
    )
    version_id = detail.json()["draft_version"]["version_id"]
    publish = portal_client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_id, "reason": "Go live"},
        headers=portal_headers(role="MANAGER", user_id="manager.demo", name="Manager Demo"),
    )
    assert publish.status_code == 200
    assert publish.json()["status"] == "ACTIVE"
    return document_id


def _patch_portal_transport(portal_client: TestClient) -> object:
    async def _get(url: str, headers: dict[str, str] | None = None, **kwargs: object):
        path = url.split("/api/", 1)[-1]
        portal_path = f"/api/{path}"
        response = portal_client.get(portal_path, headers=headers or {})
        mock_response = MagicMock()
        mock_response.status_code = response.status_code
        mock_response.json = response.json
        return mock_response

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=_get)
    return patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=client,
    )


@pytest.fixture
def governance_integration_clients(tmp_path: Path) -> tuple[TestClient, TestClient, str]:
    portal_client = TestClient(create_portal_app(_portal_settings(tmp_path)))
    document_id = _publish_markdown_document(portal_client)

    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    import asyncio

    asyncio.run(_seed_sample_events(store_path, data_dir))
    backoffice_settings = BackofficeSettings(
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
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    backoffice_client = TestClient(create_app(backoffice_settings))
    return portal_client, backoffice_client, document_id


def test_portal_publish_surfaces_in_backoffice_governance(
    governance_integration_clients: tuple[TestClient, TestClient, str],
) -> None:
    """Phase 1 §12.7: published Markdown lifecycle is visible in backoffice knowledge view."""
    portal_client, backoffice_client, document_id = governance_integration_clients

    with _patch_portal_transport(portal_client):
        response = backoffice_client.get(
            f"/api/knowledge/{document_id}/performance?days=30",
            headers=headers("KNOWLEDGE_ADMIN"),
        )

    assert response.status_code == 200
    governance = response.json()["governance"]
    assert governance["status"] == "available"
    assert governance["lifecycleStatus"] in {"PUBLISHED", "ACTIVE"}
    assert governance["formatType"] in {"MARKDOWN", "MARKDOWN_PASTE", "MARKDOWN_UPLOAD"}
    assert governance["parseStatus"] == "READY"
    assert "portalUrl" in governance

    portal_detail = portal_client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER"),
    )
    assert portal_detail.status_code == 200
    assert portal_detail.json()["document"]["status"] in {"PUBLISHED", "ACTIVE"}


def _text_pdf_bytes(text: str) -> bytes:
    return build_text_pdf_bytes(text)


def _publish_pdf_document(portal_client: TestClient) -> str:
    imported = portal_client.post(
        "/api/documents/import-pdf",
        files={"file": ("policy.pdf", _text_pdf_bytes("Remote access policy excerpt"), "application/pdf")},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert imported.status_code == 200
    payload = sample_document_payload()
    payload["title"] = imported.json()["title"]
    payload["markdown_content"] = imported.json()["markdown_content"]
    payload["change_reason"] = "Import text PDF"
    create = portal_client.post(
        "/api/documents",
        json={**payload, "source_type": "PDF"},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]
    submit = portal_client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready"},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    review_id = submit.json()["open_review"]["review_id"]
    portal_client.post(
        f"/api/reviews/{review_id}/decision",
        json={"decision": "APPROVED", "comment": "ok", "policy_exceptions": []},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    detail = portal_client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER"),
    )
    version_id = detail.json()["draft_version"]["version_id"]
    publish = portal_client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_id, "reason": "Go live"},
        headers=portal_headers(role="MANAGER", user_id="manager.demo", name="Manager Demo"),
    )
    assert publish.status_code == 200
    return document_id


def test_portal_pdf_publish_surfaces_in_backoffice_governance(
    governance_integration_clients: tuple[TestClient, TestClient, str],
) -> None:
    """Phase 1 §12.7: published text PDF lifecycle is visible in backoffice knowledge view."""
    portal_client, backoffice_client, _markdown_document_id = governance_integration_clients
    document_id = _publish_pdf_document(portal_client)

    with _patch_portal_transport(portal_client):
        response = backoffice_client.get(
            f"/api/knowledge/{document_id}/performance?days=30",
            headers=headers("KNOWLEDGE_ADMIN"),
        )

    assert response.status_code == 200
    governance = response.json()["governance"]
    assert governance["status"] == "available"
    assert governance["formatType"] == "PDF"
    assert governance["parseStatus"] == "READY"
