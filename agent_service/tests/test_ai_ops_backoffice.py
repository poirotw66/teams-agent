from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.file_store import FileOperationalStore
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.services.query_service import BackofficeQueryService
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
            actor_ref="user-demo-vpn-001",
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
            event_id=f"{occurrence_id}:route.selected",
            event_type="route.selected",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_type_id="vpn.connection_failed",
            payload={"route": "KNOWLEDGE"},
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
            event_id=f"{occurrence_id}:knowledge.answered",
            event_type="knowledge.answered",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_type_id="vpn.connection_failed",
            payload={
                "resultType": "KNOWLEDGE_ANSWERED",
                "answerMasked": "請確認 VPN 密碼未鎖定後再試一次。",
                "documentId": "vpn-password-lockout",
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
        OperationalEvent(
            event_id="corr-1:usage:1",
            event_type="usage.recorded",
            occurred_at=now + timedelta(minutes=3),
            conversation_id="conv-1",
            correlation_id="corr-1",
            issue_type_id="vpn.connection_failed",
            payload={
                "model": "gpt-4.1",
                "provider": "openai",
                "inputTokens": 120,
                "outputTokens": 45,
                "estimatedCostUsd": 0.0025,
                "pricingVersion": "v1",
                "llmCallCount": 1,
            },
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
    from agent_service.operations.audit_stores import MemoryAuditStore
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
        export_format="json",
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


def test_routes_summary(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/routes/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["routeDistribution"][0]["route"] == "KNOWLEDGE"


def test_query_audit_recorded(seeded_backoffice_client: TestClient) -> None:
    seeded_backoffice_client.get("/api/operations/summary?days=7", headers=headers())
    audit = seeded_backoffice_client.get("/api/audit-events", headers=headers("AUDITOR"))
    actions = {item["action"] for item in audit.json()["items"]}
    assert "query.operations_summary" in actions


def test_file_audit_store_persists(tmp_path: Path) -> None:
    from agent_service.operations.audit import build_audit_event
    from agent_service.operations.audit_stores import FileAuditStore

    store = FileAuditStore(tmp_path / "audit")
    event = build_audit_event(
        actor_id="owner.demo",
        actor_role="SERVICE_OWNER",
        action="export.create",
        target_type="export_job",
        target_id="job-1",
    )

    async def run() -> None:
        await store.append(event)
        page, _ = await store.list_events(limit=10)
        assert len(page) == 1

    asyncio.run(run())
    assert (tmp_path / "audit" / "audit_events.jsonl").is_file()


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
    download = backoffice_client.get(f"/api/exports/{job_id}/download", headers=headers())
    assert download.status_code == 200
    audit = backoffice_client.get("/api/audit-events", headers=headers("AUDITOR"))
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()["items"]}
    assert "export.create" in actions
    assert "export.download" in actions


def test_export_download_returns_csv_attachment(backoffice_client: TestClient) -> None:
    created = backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={
            "export_type": "operations_summary",
            "reason": "CSV download test",
            "days": 7,
            "export_format": "csv",
            "preset": "7d",
        },
    )
    job_id = created.json()["jobId"]
    for _ in range(20):
        fetched = backoffice_client.get(f"/api/exports/{job_id}", headers=headers())
        if fetched.json()["status"] == "COMPLETED":
            break
    download = backoffice_client.get(f"/api/exports/{job_id}/download", headers=headers())
    assert download.status_code == 200
    assert "text/csv" in download.headers.get("content-type", "")
    assert "attachment" in download.headers.get("content-disposition", "")


def test_header_auth_blocked_outside_dev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_DEPLOYMENT_ENV", "prod")
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
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    client = TestClient(create_app(settings))
    response = client.get("/api/operations/summary", headers=headers())
    assert response.status_code == 401


def test_entra_auth_accepts_bearer_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import base64
    import json

    monkeypatch.setenv("AI_OPS_ENTRA_VALIDATE_JWT", "false")
    payload = {
        "oid": "entra-user-1",
        "name": "Entra User",
        "roles": ["AI_OPS_SERVICE_OWNER"],
        "owner_units": "IT Service Desk",
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    token = f"header.{encoded}.signature"

    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="ENTRA",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id="tenant-demo",
        entra_client_id="client-demo",
    )
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/capabilities",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "SERVICE_OWNER"


def test_issue_routes_endpoint(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/issues/vpn.connection_failed/routes?days=30",
        headers=headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["issueTypeId"] == "vpn.connection_failed"
    assert body["routes"]


def test_export_audit_fail_closed(tmp_path: Path) -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit_errors import AuditWriteError
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_service import ExportJobService

    class FailingAuditStore(MemoryAuditStore):
        async def append(self, event) -> None:
            raise RuntimeError("audit unavailable")

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
    )
    service = ExportJobService(
        audit_store=FailingAuditStore(),
        store_path=tmp_path / "exports",
        environment="dev",
    )

    async def runner() -> dict[str, object]:
        return {"conversationCount": 0}

    import asyncio

    with pytest.raises(AuditWriteError):
        asyncio.run(
            service.create_job(
                actor=actor,
                export_type="operations_summary",
                reason="fail closed test",
                days=7,
                runner=runner,
            )
        )


def test_export_worker_failure_records_audit(tmp_path: Path) -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_service import ExportJobService

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
    )

    async def run() -> tuple[str, list]:
        audit_store = MemoryAuditStore()
        service = ExportJobService(
            audit_store=audit_store,
            store_path=tmp_path / "failed-exports",
            environment="dev",
        )

        async def runner() -> dict[str, object]:
            raise ValueError("invalid export data")

        job = await service.create_job(
            actor=actor,
            export_type="issues_summary",
            reason="failure audit test",
            days=7,
            runner=runner,
        )
        for _ in range(10):
            await asyncio.sleep(0)
            current = await service.get_job(job.job_id, actor=actor)
            if current and current.status == "FAILED":
                break
        events, _ = await audit_store.list_events()
        return current.status, events  # type: ignore[union-attr]

    status, events = asyncio.run(run())
    assert status == "FAILED"
    failure = next(event for event in events if event.action == "export.failed")
    assert failure.after == {
        "exportType": "issues_summary",
        "exportFormat": "json",
        "status": "FAILED",
        "errorType": "ValueError",
    }


def test_export_rate_limiter_blocks_excess_requests() -> None:
    from ai_ops_backoffice.services.rate_limit import ExportRateLimiter, RateLimitExceeded

    limiter = ExportRateLimiter(max_exports_per_hour=1)
    limiter.check("owner.demo")
    with pytest.raises(RateLimitExceeded):
        limiter.check("owner.demo")


def test_reconciliation_matches_seeded_summary(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/admin/reconciliation/operations-summary?days=30",
        headers=headers("SYSTEM_ADMIN"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["allMatch"] is True
    assert body["eventCount"] >= 1
    assert all(item["match"] for item in body["checks"])


def test_costs_summary_groups_by_route_and_issue(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/costs/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["totalEstimatedCostUsd"] == 0.0025
    assert body["byRoute"][0]["route"] == "KNOWLEDGE"
    assert body["byRoute"][0]["estimatedCostUsd"] == 0.0025
    assert body["byIssueType"][0]["issueTypeId"] == "vpn.connection_failed"
    assert body["byIssueType"][0]["estimatedCostUsd"] == 0.0025


def test_issues_summary_includes_hierarchy(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/issues/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["hierarchy"]
    assert body["trends"]
    vpn_issue = next(
        item for item in body["items"] if item["issueTypeId"] == "vpn.connection_failed"
    )
    assert vpn_issue["negativeFeedbackRate"] == 1.0
    assert vpn_issue["handoffRate"] >= 1.0
    assert vpn_issue["estimatedCostUsd"] == 0.0025


def test_costs_summary_includes_twd(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/costs/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["totalEstimatedCostTwd"] > 0
    assert body["usdTwdExchangeRate"] == 31.70


def test_conversation_detail_includes_correlation_and_masking(
    seeded_backoffice_client: TestClient,
) -> None:
    response = seeded_backoffice_client.get("/api/conversations/conv-1", headers=headers())
    assert response.status_code == 200
    body = response.json()
    turn = body["turns"][0]
    assert turn["correlationId"] == "corr-1"
    assert turn["masked"] is True
    assert turn["issueTypeId"] == "vpn.connection_failed"
    assert turn["route"] == "KNOWLEDGE"
    assert turn["model"] == "gpt-4.1"
    assert turn["resultType"] == "KNOWLEDGE_ANSWERED"
    assert turn["answerMasked"]
    assert turn["feedbackRating"] == "DOWN"
    assert turn["resolvedStatus"] == "UNRESOLVED"
    assert turn["handoffStatus"] == "OFFERED"
    assert turn["resultType"] == "KNOWLEDGE_ANSWERED"
    assert turn["answerMasked"] == "請確認 VPN 密碼未鎖定後再試一次。"
    assert "vpn-password-lockout" in turn["documentIds"]


def test_conversation_unmask_requires_capability_and_reason(
    seeded_backoffice_client: TestClient,
) -> None:
    forbidden = seeded_backoffice_client.get(
        "/api/conversations/conv-1",
        headers=headers("SERVICE_OWNER"),
        params={"unmask_reason": "incident review"},
    )
    assert forbidden.status_code == 403

    short_reason = seeded_backoffice_client.get(
        "/api/conversations/conv-1",
        headers=headers("KNOWLEDGE_ADMIN"),
        params={"unmask_reason": "ab"},
    )
    assert short_reason.status_code == 400

    authorized = seeded_backoffice_client.get(
        "/api/conversations/conv-1",
        headers=headers("KNOWLEDGE_ADMIN"),
        params={"unmask_reason": "incident review"},
    )
    assert authorized.status_code == 200
    body = authorized.json()
    assert body["unmaskAuthorized"] is True
    assert body["turns"][0]["masked"] is False

    audit = seeded_backoffice_client.get("/api/audit-events", headers=headers("AUDITOR"))
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()["items"]}
    assert "query.conversation_unmasked" in actions


def test_capabilities_hide_restricted_nav_for_service_owner(
    seeded_backoffice_client: TestClient,
) -> None:
    response = seeded_backoffice_client.get("/api/capabilities", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert "ops.health.read" not in body["capabilities"]
    assert "ops.audit.read" not in body["capabilities"]
    assert "ops.knowledge.read" not in body["capabilities"]


def test_xlsx_export_job_download(seeded_backoffice_client: TestClient) -> None:
    created = seeded_backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={
            "export_type": "costs_summary",
            "reason": "UAT xlsx export",
            "days": 30,
            "export_format": "xlsx",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["jobId"]
    for _ in range(20):
        fetched = seeded_backoffice_client.get(f"/api/exports/{job_id}", headers=headers())
        assert fetched.status_code == 200
        if fetched.json()["status"] == "COMPLETED":
            break
    assert fetched.json()["status"] == "COMPLETED"
    assert "exportMetadata" in fetched.json()["result"]
    download = seeded_backoffice_client.get(
        f"/api/exports/{job_id}/download",
        headers=headers(),
    )
    assert download.status_code == 200
    assert download.content.startswith(b"PK")
    assert (
        download.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_operations_summary_includes_data_freshness(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/operations/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["latestEventAt"] is not None
    assert body["dataFreshnessMinutes"] is not None


def test_reconciliation_costs_and_issues_match(seeded_backoffice_client: TestClient) -> None:
    costs = seeded_backoffice_client.get(
        "/api/admin/reconciliation/costs-summary?days=30",
        headers=headers("SYSTEM_ADMIN"),
    )
    assert costs.status_code == 200
    assert costs.json()["allMatch"] is True

    issues = seeded_backoffice_client.get(
        "/api/admin/reconciliation/issues-summary?days=30",
        headers=headers("SYSTEM_ADMIN"),
    )
    assert issues.status_code == 200
    assert issues.json()["allMatch"] is True


def test_admin_retention_purge_removes_expired_events(tmp_path: Path) -> None:
    import asyncio

    from agent_service.operations.contracts import OperationalEvent, utc_now

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
    ingestion = EventIngestionService(
        FileOperationalStore(store_path),
        _ops_settings(data_dir, store_path),
    )
    now = utc_now()

    async def add_expired_event() -> None:
        await ingestion.ingest(
            OperationalEvent(
                event_id="expired-turn",
                event_type="turn.received",
                occurred_at=now,
                correlation_id="corr-expired",
                retention_expires_at=now - timedelta(seconds=1),
                payload={"messageMasked": "expired"},
            )
        )

    asyncio.run(add_expired_event())
    forbidden = client.post("/api/admin/retention/purge", headers=headers())
    assert forbidden.status_code == 403

    response = client.post("/api/admin/retention/purge", headers=headers("SYSTEM_ADMIN"))
    assert response.status_code == 200
    assert response.json()["removed"] >= 1


def test_query_audit_fail_closed(tmp_path: Path) -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit_errors import AuditWriteError
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.query_audit import record_query_audit

    class FailingAuditStore(MemoryAuditStore):
        async def append(self, event) -> None:
            raise RuntimeError("audit unavailable")

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
    )

    async def run() -> None:
        await record_query_audit(
            FailingAuditStore(),
            actor=actor,
            action="query.operations_summary",
            target_id="operations_summary",
            environment="dev",
        )

    with pytest.raises(AuditWriteError):
        asyncio.run(run())


def test_conversations_filter_by_handoff(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/conversations?days=30&handoff=true",
        headers=headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    assert body["items"][0]["conversationId"] == "conv-1"


def test_metrics_definitions_endpoint(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/metrics/definitions", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["definitions"]["conversation_count"]
    assert body["metricsDefinitionVersion"] == "v1"


def test_export_rejects_invalid_format(backoffice_client: TestClient) -> None:
    response = backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={
            "export_type": "operations_summary",
            "reason": "invalid format test",
            "days": 7,
            "export_format": "pdf",
        },
    )
    assert response.status_code == 400


def test_health_summary_simulated_anomalies(tmp_path: Path) -> None:
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
    body = response.json()
    assert body["simulatedAnomalies"] is True
    statuses = {item["id"]: item["status"] for item in body["components"]}
    assert statuses["agent-service"] == "DEGRADED"
    assert statuses["agent-retrieval-search"] == "DOWN"
    assert statuses["ticket-service"] == "DOWN"


def test_health_summary_includes_active_knowledge_release(tmp_path: Path) -> None:
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
    )
    portal_response = MagicMock(status_code=200)
    release_response = MagicMock(status_code=200)
    release_response.json.return_value = [
        {
            "release_id": "release-2026-09-03",
            "status": "ACTIVE",
            "manifest": [{"document_id": "doc-1"}, {"document_id": "doc-2"}],
            "created_at": "2026-09-03T01:00:00+00:00",
            "activated_at": "2026-09-03T02:00:00+00:00",
            "index_setting_version": "index-v3",
        }
    ]
    http_client = MagicMock()
    http_client.__aenter__ = AsyncMock(return_value=http_client)
    http_client.__aexit__ = AsyncMock(return_value=False)
    http_client.get = AsyncMock(side_effect=[portal_response, release_response])

    with patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=http_client,
    ):
        response = TestClient(create_app(settings)).get(
            "/api/health/summary",
            headers=headers("SYSTEM_ADMIN"),
        )

    assert response.status_code == 200
    release = next(
        item for item in response.json()["components"]
        if item["id"] == "knowledge-release"
    )
    assert release == {
        "id": "knowledge-release",
        "status": "READY",
        "note": "Active Knowledge release is available.",
        "releaseId": "release-2026-09-03",
        "publishedAt": "2026-09-03T02:00:00+00:00",
        "indexStatus": "READY",
        "documentCount": 2,
        "indexSettingVersion": "index-v3",
        "telemetryStatus": "NO_DATA",
        "requestCount": 0,
        "availabilityRate": None,
        "errorRate": None,
        "timeoutRate": None,
        "p50LatencyMs": None,
        "p95LatencyMs": None,
    }


def test_health_summary_includes_24_hour_operational_metrics(
    seeded_backoffice_client: TestClient,
) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"retrieval": "ready", "chunks": 1, "hits": []}
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    with patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=client,
    ):
        result = seeded_backoffice_client.get(
            "/api/health/summary",
            headers=headers("SYSTEM_ADMIN"),
        )

    assert result.status_code == 200
    body = result.json()
    assert body["telemetryWindowHours"] == 24
    components = {item["id"]: item for item in body["components"]}
    assert components["agent-service"]["requestCount"] == 1
    assert components["agent-service"]["availabilityRate"] == 1.0
    assert components["llm-api"]["requestCount"] == 1
    assert components["teams-adapter"]["telemetryStatus"] == "NO_DATA"


def test_health_metric_summary_separates_failures_and_timeouts() -> None:
    summary = BackofficeQueryService._health_metric_summary(
        [("SUCCESS", 100.0), ("FAILED", 200.0), ("TIMEOUT", 300.0)]
    )

    assert summary["requestCount"] == 3
    assert summary["availabilityRate"] == 0.3333
    assert summary["errorRate"] == 0.3333
    assert summary["timeoutRate"] == 0.3333
    assert summary["p50LatencyMs"] == 200.0


def test_operations_summary_rejects_excessive_custom_period(
    backoffice_client: TestClient,
) -> None:
    response = backoffice_client.get(
        "/api/operations/summary"
        "?start_date=2020-01-01T00:00:00%2B00:00"
        "&end_date=2026-01-01T00:00:00%2B00:00",
        headers=headers(),
    )
    assert response.status_code == 400
