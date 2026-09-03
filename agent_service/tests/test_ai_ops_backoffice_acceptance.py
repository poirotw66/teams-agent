from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from test_ai_ops_backoffice import _ops_settings, _seed_sample_events, headers

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings


@pytest.fixture
def acceptance_client(tmp_path: Path) -> TestClient:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    import asyncio

    asyncio.run(_seed_sample_events(store_path, data_dir))
    settings = BackofficeSettings(
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
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    return TestClient(create_app(settings))


def test_uat_negative_feedback_drill_down_path(acceptance_client: TestClient) -> None:
    """Phase 1 §12.10: negative feedback -> conversation -> issue -> document."""
    feedback = acceptance_client.get(
        "/api/feedback?days=30&rating=DOWN",
        headers=headers(),
    )
    assert feedback.status_code == 200
    item = feedback.json()["items"][0]
    assert item["rating"] == "DOWN"
    assert item["conversationId"] == "conv-1"

    conversation = acceptance_client.get(
        f"/api/conversations/{item['conversationId']}",
        headers=headers(),
    )
    assert conversation.status_code == 200
    assert conversation.json()["turns"]

    trace = item["trace"]
    assert trace["issueTypeId"] == "vpn.connection_failed"
    assert "vpn-password-lockout" in trace["documentIds"]

    routes = acceptance_client.get(
        f"/api/issues/{trace['issueTypeId']}/routes?days=30",
        headers=headers(),
    )
    assert routes.status_code == 200
    assert routes.json()["routes"]

    document = acceptance_client.get(
        "/api/knowledge/vpn-password-lockout/performance?days=30",
        headers=headers("KNOWLEDGE_ADMIN"),
    )
    assert document.status_code == 200
    assert document.json()["hitCount"] >= 1


def _mock_portal_response(
    *,
    status_code: int = 200,
    payload: dict | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload or {}
    return response


def _patch_portal_client(response: MagicMock) -> object:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    return patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=client,
    )


def test_uat_document_governance_markdown_from_portal(acceptance_client: TestClient) -> None:
    """Phase 1 §12.7: backoffice surfaces Knowledge Portal lifecycle and index status."""
    portal_payload = {
        "document": {
            "status": "PUBLISHED",
            "current_published_version_id": "ver-published",
            "draft_version_id": None,
        },
        "published_version": {
            "source_type": "MARKDOWN",
            "parse_preview": {"chunkCount": 3},
        },
        "status_label": "Published",
    }
    with _patch_portal_client(_mock_portal_response(payload=portal_payload)):
        response = acceptance_client.get(
            "/api/knowledge/vpn-password-lockout/performance?days=30",
            headers=headers("KNOWLEDGE_ADMIN"),
        )
    assert response.status_code == 200
    governance = response.json()["governance"]
    assert governance["status"] == "available"
    assert governance["formatType"] == "MARKDOWN"
    assert governance["parseStatus"] == "READY"
    assert governance["lifecycleStatus"] == "PUBLISHED"
    assert "portalUrl" in governance


def test_uat_document_governance_text_pdf_from_portal(acceptance_client: TestClient) -> None:
    """Phase 1 §12.7: text PDF documents expose parse and index status via portal proxy."""
    portal_payload = {
        "document": {
            "status": "PUBLISHED",
            "current_published_version_id": "ver-pdf",
        },
        "published_version": {
            "source_type": "PDF",
            "parse_preview": {"pageCount": 2, "textExtracted": True},
        },
        "status_label": "Published",
    }
    with _patch_portal_client(_mock_portal_response(payload=portal_payload)):
        response = acceptance_client.get(
            "/api/knowledge/vpn-password-lockout/performance?days=30",
            headers=headers("KNOWLEDGE_ADMIN"),
        )
    governance = response.json()["governance"]
    assert governance["status"] == "available"
    assert governance["formatType"] == "PDF"
    assert governance["parseStatus"] == "READY"


def test_uat_knowledge_inventory_enriches_governance_and_performance(
    acceptance_client: TestClient,
) -> None:
    document = {
        "document_id": "vpn-password-lockout",
        "title": "VPN Password Lockout",
        "summary": "VPN support guide",
        "owner_unit_id": "IT Service Desk",
        "status": "PUBLISHED",
        "current_published_version_id": "ver-published",
        "draft_version_id": None,
        "updated_at": "2026-09-03T00:00:00+00:00",
    }
    detail = {
        "document": document,
        "published_version": {
            "source_type": "MARKDOWN_UPLOAD",
            "parse_preview": {"segments": []},
        },
        "status_label": "Published",
    }
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(
        side_effect=[
            _mock_portal_response(payload={"items": [document], "total": 1}),
            _mock_portal_response(payload=detail),
        ]
    )
    with patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=client,
    ):
        response = acceptance_client.get(
            "/api/knowledge?status=PUBLISHED&days=30",
            headers=headers("KNOWLEDGE_ADMIN"),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["documentId"] == "vpn-password-lockout"
    assert item["formatType"] == "MARKDOWN_UPLOAD"
    assert item["parseStatus"] == "READY"
    assert item["hitCount"] >= 1
    assert item["negativeFeedbackCount"] == 1
    assert item["issueTypeDistribution"][0]["issueTypeId"] == "vpn.connection_failed"


def test_uat_knowledge_inventory_applies_owner_scope_and_cursor(
    acceptance_client: TestClient,
) -> None:
    documents = [
        {
            "document_id": "doc-a",
            "title": "A",
            "owner_unit_id": "IT Service Desk",
            "status": "PUBLISHED",
        },
        {
            "document_id": "doc-b",
            "title": "B",
            "owner_unit_id": "IT Service Desk",
            "status": "PUBLISHED",
        },
        {
            "document_id": "doc-secret",
            "title": "HR Secret",
            "owner_unit_id": "HR",
            "status": "PUBLISHED",
        },
    ]
    detail_response = _mock_portal_response(
        payload={
            "document": {"status": "PUBLISHED"},
            "published_version": {"source_type": "MARKDOWN_PASTE"},
        }
    )

    def portal_client() -> MagicMock:
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(
            side_effect=[
                _mock_portal_response(payload={"items": documents, "total": 3}),
                detail_response,
            ]
        )
        return client

    with patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=portal_client(),
    ):
        first = acceptance_client.get(
            "/api/knowledge?limit=1",
            headers=headers("KNOWLEDGE_ADMIN"),
        )
    assert first.status_code == 200
    assert first.json()["total"] == 2
    assert [item["documentId"] for item in first.json()["items"]] == ["doc-a"]
    assert first.json()["nextCursor"] == "doc-a"

    with patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=portal_client(),
    ):
        second = acceptance_client.get(
            "/api/knowledge?limit=1&cursor=doc-a",
            headers=headers("KNOWLEDGE_ADMIN"),
        )
    assert second.status_code == 200
    assert second.json()["total"] == 2
    assert [item["documentId"] for item in second.json()["items"]] == ["doc-b"]
    assert second.json()["nextCursor"] is None


def test_uat_knowledge_performance_export_uses_scoped_inventory(
    acceptance_client: TestClient,
) -> None:
    document = {
        "document_id": "vpn-password-lockout",
        "title": "VPN Password Lockout",
        "owner_unit_id": "IT Service Desk",
        "status": "PUBLISHED",
    }
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(
        side_effect=[
            _mock_portal_response(payload={"items": [document], "total": 1}),
            _mock_portal_response(
                payload={
                    "document": document,
                    "published_version": {"source_type": "MARKDOWN_PASTE"},
                }
            ),
        ]
    )
    with patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=client,
    ):
        created = acceptance_client.post(
            "/api/exports",
            headers=headers("KNOWLEDGE_ADMIN"),
            json={
                "export_type": "knowledge_performance",
                "reason": "Phase 1 UAT",
                "days": 30,
            },
        )
        assert created.status_code == 200
        job_id = created.json()["jobId"]
        for _ in range(50):
            job = acceptance_client.get(
                f"/api/exports/{job_id}",
                headers=headers("KNOWLEDGE_ADMIN"),
            )
            if job.json()["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(0.01)
        assert job.json()["status"] == "COMPLETED"
        download = acceptance_client.get(
            f"/api/exports/{job_id}/download",
            headers=headers("KNOWLEDGE_ADMIN"),
        )

    assert download.status_code == 200
    exported = download.json()
    assert exported["exportMetadata"]["exportType"] == "knowledge_performance"
    assert exported["data"]["items"][0]["documentId"] == "vpn-password-lockout"


def test_knowledge_export_requires_knowledge_capability(
    acceptance_client: TestClient,
) -> None:
    response = acceptance_client.post(
        "/api/exports",
        headers=headers("SERVICE_OWNER"),
        json={
            "export_type": "knowledge_performance",
            "reason": "Should be forbidden",
            "days": 30,
        },
    )
    assert response.status_code == 403


def test_feedback_export_requires_feedback_capability(
    acceptance_client: TestClient,
) -> None:
    response = acceptance_client.post(
        "/api/exports",
        headers=headers("AI_ADMIN"),
        json={
            "export_type": "feedback",
            "reason": "forbidden feedback export",
            "days": 30,
        },
    )
    assert response.status_code == 403


def test_export_rejects_unknown_type_before_creating_job(
    acceptance_client: TestClient,
) -> None:
    response = acceptance_client.post(
        "/api/exports",
        headers=headers("SERVICE_OWNER"),
        json={"export_type": "raw_events", "reason": "invalid export", "days": 30},
    )
    assert response.status_code == 400


def test_uat_feedback_export_applies_visible_filters(
    acceptance_client: TestClient,
) -> None:
    response = acceptance_client.post(
        "/api/exports",
        headers=headers("SERVICE_OWNER"),
        json={
            "export_type": "feedback",
            "reason": "filtered quality review",
            "days": 30,
            "rating": "DOWN",
            "feedback_reason": "wrong_answer",
            "resolved_status": "UNRESOLVED",
            "handoff": True,
        },
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    for _ in range(20):
        completed = acceptance_client.get(f"/api/exports/{job_id}", headers=headers())
        if completed.json()["status"] == "COMPLETED":
            break
        time.sleep(0.05)
    exported = completed.json()["result"]
    assert exported["exportMetadata"]["queryFilters"] == {
        "handoff": True,
        "rating": "DOWN",
        "reason": "wrong_answer",
        "resolvedStatus": "UNRESOLVED",
    }
    assert exported["exportMetadata"]["recordCount"] == 1
    assert exported["data"]["items"][0]["rating"] == "DOWN"


def test_uat_route_export_applies_issue_filter(
    acceptance_client: TestClient,
) -> None:
    response = acceptance_client.post(
        "/api/exports",
        headers=headers("SERVICE_OWNER"),
        json={
            "export_type": "routes_summary",
            "reason": "filtered route review",
            "days": 30,
            "issue_type_id": "vpn.connection_failed",
        },
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    for _ in range(20):
        completed = acceptance_client.get(f"/api/exports/{job_id}", headers=headers())
        if completed.json()["status"] == "COMPLETED":
            break
        time.sleep(0.05)
    exported = completed.json()["result"]
    assert exported["exportMetadata"]["queryFilters"] == {
        "issueTypeId": "vpn.connection_failed"
    }
    assert exported["data"]["byIssueType"][0]["issueTypeId"] == "vpn.connection_failed"
    assert exported["exportMetadata"]["recordCount"] == len(
        exported["data"]["routeDistribution"]
    )
    assert exported["exportMetadata"]["fields"] == ["count", "route"]


def test_uat_conversation_export_is_filtered_and_masked(
    acceptance_client: TestClient,
) -> None:
    response = acceptance_client.post(
        "/api/exports",
        headers=headers("SERVICE_OWNER"),
        json={
            "export_type": "conversations",
            "reason": "conversation investigation",
            "days": 30,
            "issue_type_id": "vpn.connection_failed",
            "has_feedback": True,
        },
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    for _ in range(20):
        completed = acceptance_client.get(
            f"/api/exports/{job_id}",
            headers=headers("SERVICE_OWNER"),
        )
        if completed.json()["status"] == "COMPLETED":
            break
    exported = completed.json()["result"]
    assert exported["exportMetadata"]["exportType"] == "conversations"
    assert exported["exportMetadata"]["queryFilters"] == {
        "issueTypeId": "vpn.connection_failed",
        "hasFeedback": True,
    }
    assert exported["data"]["items"][0]["conversationId"] == "conv-1"
    assert "messageMasked" not in exported["data"]["items"][0]
    assert "events" not in exported["data"]["items"][0]


def test_document_performance_excludes_unpublished_hits(tmp_path: Path) -> None:
    import asyncio

    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    asyncio.run(_seed_sample_events(store_path, data_dir))
    settings = BackofficeSettings(
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
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    client = TestClient(create_app(settings))
    from agent_service.operations.contracts import OperationalEvent, utc_now
    from agent_service.operations.ingestion import EventIngestionService
    from agent_service.operations.stores.file_store import FileOperationalStore

    async def add_draft_hit() -> None:
        ingestion = EventIngestionService(
            FileOperationalStore(store_path),
            _ops_settings(data_dir, store_path),
        )
        await ingestion.ingest(
            OperationalEvent(
                event_id="draft-hit",
                event_type="knowledge.retrieved",
                occurred_at=utc_now(),
                conversation_id="conv-draft",
                correlation_id="corr-draft",
                payload={"documentId": "vpn-password-lockout", "isDraft": True},
            )
        )

    asyncio.run(add_draft_hit())
    response = client.get(
        "/api/knowledge/vpn-password-lockout/performance?days=30",
        headers=headers("KNOWLEDGE_ADMIN"),
    )
    assert response.status_code == 200
    assert response.json()["hitCount"] == 2


def test_uat_actor_ref_conversation_lookup(acceptance_client: TestClient) -> None:
    """Phase 1 §12.3: authorized user can find conversations by pseudonymous actor ref."""
    response = acceptance_client.get(
        "/api/conversations?preset=6m&actor_ref=user-demo-vpn-001",
        headers=headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert any(item["conversationId"] == "conv-1" for item in body["items"])
    assert all(item["actorRef"] == "user-demo-vpn-001" for item in body["items"])


def test_uat_missing_cost_not_counted_as_zero(tmp_path: Path) -> None:
    """Phase 1 §12.2: usage without pricing must not be treated as zero-cost."""
    import asyncio

    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    asyncio.run(_seed_sample_events(store_path, data_dir))
    settings = BackofficeSettings(
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
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    from agent_service.operations.contracts import OperationalEvent, utc_now
    from agent_service.operations.ingestion import EventIngestionService
    from agent_service.operations.stores.file_store import FileOperationalStore

    async def add_missing_cost_usage() -> None:
        ingestion = EventIngestionService(
            FileOperationalStore(store_path),
            _ops_settings(data_dir, store_path),
        )
        await ingestion.ingest(
            OperationalEvent(
                event_id="usage-missing-cost",
                event_type="usage.recorded",
                occurred_at=utc_now(),
                conversation_id="conv-1",
                correlation_id="corr-missing",
                issue_type_id="vpn.connection_failed",
                payload={
                    "model": "gpt-4.1",
                    "provider": "openai",
                    "inputTokens": 50,
                    "outputTokens": 20,
                    "pricingVersion": "unknown",
                },
            )
        )

    asyncio.run(add_missing_cost_usage())
    client = TestClient(create_app(settings))
    response = client.get("/api/costs/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["missingCostEventCount"] >= 1
    assert body["totalEstimatedCostUsd"] == 0.0025
    assert any(
        item["pricingVersion"] == "unknown"
        for item in body.get("pricingVersionsObserved", [])
    )


def test_uat_period_presets_supported(acceptance_client: TestClient) -> None:
    for preset in ("today", "7d", "30d", "6m"):
        response = acceptance_client.get(
            f"/api/issues/summary?preset={preset}",
            headers=headers(),
        )
        assert response.status_code == 200
        assert response.json()["periodPreset"] == preset


def test_uat_health_detects_simulated_anomalies(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        simulate_health_anomalies=True,
    )
    client = TestClient(create_app(settings))
    response = client.get("/api/health/summary", headers=headers("SYSTEM_ADMIN"))
    assert response.status_code == 200
    degraded = [
        item["id"]
        for item in response.json()["components"]
        if item["status"] in {"DEGRADED", "DOWN"}
    ]
    assert "agent-service" in degraded
    assert "agent-retrieval-search" in degraded
    assert "ticket-service" in degraded


def test_uat_export_records_audit_and_metadata(acceptance_client: TestClient) -> None:
    created = acceptance_client.post(
        "/api/exports",
        headers=headers(),
        json={
            "export_type": "issues_summary",
            "reason": "acceptance export",
            "days": 7,
            "export_format": "csv",
            "preset": "7d",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["jobId"]
    completed = None
    for _ in range(20):
        completed = acceptance_client.get(f"/api/exports/{job_id}", headers=headers())
        if completed.json()["status"] == "COMPLETED":
            break
        time.sleep(0.05)
    assert completed is not None
    assert completed.json()["status"] == "COMPLETED"
    metadata = completed.json()["result"]["exportMetadata"]
    assert metadata["exportType"] == "issues_summary"
    assert metadata["period"]["preset"] == "7d"
    assert metadata["recordCount"] == len(completed.json()["result"]["data"]["items"])
    assert "issueTypeId" in metadata["fields"]

    audit = acceptance_client.get("/api/audit-events", headers=headers("AUDITOR"))
    audit_items = audit.json()["items"]
    actions = {item["action"] for item in audit_items}
    assert "export.create" in actions
    assert "export.complete" in actions
    created_audit = next(item for item in audit_items if item["action"] == "export.create")
    assert created_audit["reason"] == "acceptance export"
    assert created_audit["after"]["periodPreset"] == "7d"
    completion = next(item for item in audit_items if item["action"] == "export.complete")
    assert completion["after"]["recordCount"] == metadata["recordCount"]
    assert completion["after"]["fields"] == metadata["fields"]
