"""REQ-024 Agent Service health telemetry ingest endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.operations.runtime import build_ops_runtime
from agent_service.operations.settings import OpsSettings
from agent_service.settings import RagSettings


def test_agent_health_telemetry_endpoint_ingests_event(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn.md").write_text("# VPN\n\nhelp", encoding="utf-8")
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        min_score=0.05,
        service_token="svc-token",
    )
    repo_data = Path(__file__).resolve().parents[2] / "data" / "ops"
    ops = OpsSettings(
        enabled=True,
        store_mode="MEMORY",
        store_path=tmp_path / "ops-events",
        taxonomy_path=repo_data / "issue_taxonomy_v1.json",
        metrics_path=repo_data / "metrics_definitions_v1.json",
        environment="test",
        default_retention_days=365,
        transcript_retention_days=365,
        audit_retention_days=1095,
        async_emit=False,
        classification_rules_path=repo_data / "issue_classification_rules.json",
        firestore_project=None,
        firestore_database=None,
        firestore_collection="operational_events",
        bigquery_enabled=False,
        bigquery_project=None,
        bigquery_dataset="ai_ops_analytics",
        bigquery_table="operational_events",
        audit_store_mode="MEMORY",
        audit_firestore_collection="audit_events",
        delivery_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        client.app.state.ops_runtime = build_ops_runtime(ops)
        response = client.post(
            "/agent/ops/health-telemetry",
            headers={"Authorization": "Bearer svc-token"},
            json={
                "component": "teams_adapter",
                "status": "TIMEOUT",
                "elapsedMs": 9000,
                "correlationId": "corr-timeout",
                "attributionScope": "ADAPTER_REPLY",
                "errorType": "AgentGatewayTimeoutError",
            },
        )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
