from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.file_store import FileOperationalStore
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings


def _ops_settings(data_dir: Path, store_path: Path) -> OpsSettings:
    return OpsSettings(
        enabled=True,
        store_mode="FILE",
        store_path=store_path,
        taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        environment="dev",
        default_retention_days=365,
        transcript_retention_days=365,
        audit_retention_days=1095,
        async_emit=True,
        firestore_project=None,
        firestore_database=None,
        firestore_collection="operational_events",
        bigquery_enabled=False,
        bigquery_project=None,
        bigquery_dataset="ai_ops_analytics",
        bigquery_table="operational_events",
        audit_store_mode="MEMORY",
        audit_firestore_collection="audit_events",
    )


async def _seed_sample_events(store_path: Path, data_dir: Path) -> None:
    settings = _ops_settings(data_dir, store_path)
    ingestion = EventIngestionService(FileOperationalStore(store_path), settings)
    now = utc_now()
    turn_id = "turn-1"
    occurrence_id = f"{turn_id}:issue:1"
    events = [
        OperationalEvent(
            event_id="turn-1:turn.received",
            event_type="turn.received",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            payload={"messageMasked": "VPN 連線失敗"},
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:issue.extracted",
            event_type="issue.extracted",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={
                "issueId": 1,
                "descriptionMasked": "VPN 連線失敗",
                "route": "KNOWLEDGE",
            },
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:issue.classified",
            event_type="issue.classified",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={"classificationSource": "MODEL"},
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:knowledge.retrieved:1",
            event_type="knowledge.retrieved",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_type_id="vpn.connection_failed",
            payload={
                "documentId": "vpn-password-lockout",
                "chunkId": "chunk-1",
                "releaseId": "release-2025-09-01",
            },
        ),
        OperationalEvent(
            event_id="corr-1:feedback:1:DOWN",
            event_type="feedback.recorded",
            occurred_at=now + timedelta(minutes=1),
            conversation_id="conv-1",
            correlation_id="corr-1",
            payload={
                "rating": "DOWN",
                "issueId": 1,
                "reason": "wrong_answer",
                "resolvedStatus": "UNRESOLVED",
            },
        ),
        OperationalEvent(
            event_id="case-1:handoff.offered",
            event_type="handoff.offered",
            occurred_at=now + timedelta(minutes=2),
            conversation_id="conv-1",
            correlation_id="corr-1",
            payload={"status": "OFFERED"},
        ),
    ]
    await ingestion.ingest_many(events)


@pytest.fixture
def backoffice_client(tmp_path: Path) -> TestClient:
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
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def seeded_backoffice_client(tmp_path: Path) -> TestClient:
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
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    return TestClient(create_app(settings))


def headers(role: str = "SERVICE_OWNER") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": "owner.demo",
        "X-Backoffice-User-Name": "Owner Demo",
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
    }


def test_operations_summary_requires_auth(backoffice_client: TestClient) -> None:
    response = backoffice_client.get("/api/operations/summary")
    assert response.status_code == 401


def test_operations_summary_for_service_owner(backoffice_client: TestClient) -> None:
    response = backoffice_client.get("/api/operations/summary?days=7", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert "conversationCount" in body
    assert body["metricsDefinitionVersion"] == "v1"


def test_taxonomy_endpoint(backoffice_client: TestClient) -> None:
    response = backoffice_client.get("/api/taxonomy", headers=headers("AI_ADMIN"))
    assert response.status_code == 200
    assert response.json()["taxonomyVersion"] == "v1"
    assert len(response.json()["items"]) >= 20


def test_auditor_cannot_read_summary(backoffice_client: TestClient) -> None:
    response = backoffice_client.get("/api/operations/summary", headers=headers("AUDITOR"))
    assert response.status_code == 403


def test_async_export_job(backoffice_client: TestClient) -> None:
    created = backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={"export_type": "operations_summary", "reason": "UAT export", "days": 7},
    )
    assert created.status_code == 200
    job_id = created.json()["jobId"]
    fetched = backoffice_client.get(f"/api/exports/{job_id}", headers=headers())
    assert fetched.status_code == 200
    assert fetched.json()["status"] in {"QUEUED", "RUNNING", "COMPLETED"}


def test_feedback_drill_down(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/feedback?days=30&rating=DOWN&handoff=true",
        headers=headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["conversationId"] == "conv-1"
    trace = item["trace"]
    assert trace["issueTypeId"] == "vpn.connection_failed"
    assert trace["documentIds"] == ["vpn-password-lockout"]
    assert trace["handoffOccurred"] is True


def test_document_performance(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/knowledge/vpn-password-lockout/performance?days=30",
        headers=headers("KNOWLEDGE_ADMIN"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["hitCount"] >= 1
    assert body["negativeFeedbackCount"] == 1
    assert body["releaseAttribution"][0]["releaseId"] == "release-2025-09-01"


def test_export_job_expires_after_ttl(tmp_path: Path) -> None:
    from datetime import timedelta

    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit import MemoryAuditStore
    from ai_ops_backoffice.services.export_service import ExportJob, ExportJobService

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
    )
    service = ExportJobService(
        audit_store=MemoryAuditStore(),
        store_path=tmp_path / "exports",
        environment="dev",
    )
    expired_at = (utc_now() - timedelta(hours=1)).isoformat()
    service._jobs["job-expired"] = ExportJob(
        job_id="job-expired",
        export_type="operations_summary",
        status="COMPLETED",
        reason="test",
        requested_by="owner.demo",
        requested_role="SERVICE_OWNER",
        days=7,
        created_at=expired_at,
        expires_at=expired_at,
        completed_at=expired_at,
        result={"conversationCount": 0},
    )

    async def run() -> ExportJob | None:
        return await service.get_job("job-expired", actor=actor)

    import asyncio

    job = asyncio.run(run())
    assert job is not None
    assert job.status == "EXPIRED"


def test_export_audit_on_download(backoffice_client: TestClient) -> None:
    created = backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={"export_type": "feedback", "reason": "Audit test", "days": 7},
    )
    job_id = created.json()["jobId"]
    for _ in range(20):
        fetched = backoffice_client.get(f"/api/exports/{job_id}", headers=headers())
        if fetched.json()["status"] == "COMPLETED":
            break
    audit = backoffice_client.get("/api/audit-events", headers=headers("AUDITOR"))
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()["items"]}
    assert "export.create" in actions
    assert "export.download" in actions
