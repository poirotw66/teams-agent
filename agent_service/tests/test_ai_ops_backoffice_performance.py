from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_ai_ops_backoffice import _ops_settings, headers

from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.stores.file_store import FileOperationalStore
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings


async def _seed_large_event_set(store_path: Path, data_dir: Path, event_count: int = 2500) -> None:
    settings = _ops_settings(data_dir, store_path)
    ingestion = EventIngestionService(FileOperationalStore(store_path), settings)
    now = utc_now()
    events: list[OperationalEvent] = []
    for index in range(event_count):
        conversation_id = f"conv-{index % 120}"
        correlation_id = f"corr-{index}"
        turn_id = f"turn-{index}"
        occurred_at = now - timedelta(minutes=index % 10080)
        events.append(
            OperationalEvent(
                event_id=f"{turn_id}:turn.received",
                event_type="turn.received",
                occurred_at=occurred_at,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                turn_id=turn_id,
                actor_ref=f"user-{index % 40}",
                payload={"messageMasked": f"question {index}"},
            )
        )
        if index % 3 == 0:
            events.append(
                OperationalEvent(
                    event_id=f"{turn_id}:issue.extracted",
                    event_type="issue.extracted",
                    occurred_at=occurred_at,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    turn_id=turn_id,
                    issue_type_id="vpn.connection_failed",
                    payload={"issueId": index, "descriptionMasked": "VPN issue"},
                )
            )
        if index % 5 == 0:
            events.append(
                OperationalEvent(
                    event_id=f"{turn_id}:usage.recorded",
                    event_type="usage.recorded",
                    occurred_at=occurred_at,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    payload={
                        "model": "gpt-4.1",
                        "estimatedCostUsd": 0.001,
                        "elapsedMs": 1200 + (index % 50),
                        "pricingVersion": "v1",
                    },
                )
            )
    await ingestion.ingest_many(events)


@pytest.fixture
def performance_client(tmp_path: Path) -> TestClient:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    asyncio.run(_seed_large_event_set(store_path, data_dir))
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


def _p95_seconds(samples: list[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = int((len(ordered) - 1) * 0.95)
    return ordered[index]


def test_dashboard_and_conversation_queries_meet_p95_budget(
    performance_client: TestClient,
) -> None:
    """Phase 1 §11: dashboard and conversation search P95 should stay under 3 seconds."""
    samples: dict[str, list[float]] = {
        "operations_summary": [],
        "issues_summary": [],
        "conversations": [],
        "conversation_detail": [],
    }
    for _ in range(12):
        start = time.perf_counter()
        response = performance_client.get("/api/operations/summary?preset=30d", headers=headers())
        assert response.status_code == 200
        samples["operations_summary"].append(time.perf_counter() - start)

        start = time.perf_counter()
        response = performance_client.get("/api/issues/summary?preset=30d", headers=headers())
        assert response.status_code == 200
        samples["issues_summary"].append(time.perf_counter() - start)

        start = time.perf_counter()
        response = performance_client.get("/api/conversations?days=30", headers=headers())
        assert response.status_code == 200
        samples["conversations"].append(time.perf_counter() - start)

        conversation_id = response.json()["items"][0]["conversationId"]
        start = time.perf_counter()
        detail = performance_client.get(
            f"/api/conversations/{conversation_id}",
            headers=headers(),
        )
        assert detail.status_code == 200
        samples["conversation_detail"].append(time.perf_counter() - start)

    dashboard_p95 = max(
        _p95_seconds(samples["operations_summary"]),
        _p95_seconds(samples["issues_summary"]),
    )
    conversation_p95 = _p95_seconds(samples["conversations"])
    detail_p95 = _p95_seconds(samples["conversation_detail"])

    assert dashboard_p95 < 3.0, f"dashboard P95={dashboard_p95:.3f}s"
    assert conversation_p95 < 3.0, f"conversation search P95={conversation_p95:.3f}s"
    assert detail_p95 < 2.0, f"conversation detail P95={detail_p95:.3f}s"
