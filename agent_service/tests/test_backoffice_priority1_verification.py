from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_service.operations.contracts import (
    DEFAULT_TIMEZONE,
    OperationalEvent,
    utc_now,
)
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.file_store import FileOperationalStore
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.services.periods import resolve_period
from ai_ops_backoffice.settings import BackofficeSettings


def _settings(tmp_path: Path, **overrides) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    params = {
        "host": "127.0.0.1",
        "port": 8092,
        "service_token": "",
        "auth_mode": "HEADER",
        "ops_store_mode": "FILE",
        "ops_store_path": tmp_path / "events",
        "ops_taxonomy_path": data_dir / "ops" / "issue_taxonomy_v1.json",
        "ops_metrics_path": data_dir / "ops" / "metrics_definitions_v1.json",
        "ops_classification_rules_path": data_dir / "ops" / "issue_classification_rules.json",
        "ops_audit_store_mode": "FILE",
        "knowledge_portal_url": "http://127.0.0.1:8091",
        "agent_api_url": "http://127.0.0.1:8000",
        "adapter_api_url": "http://127.0.0.1:3978",
        "ticket_service_url": None,
        "default_owner_unit_id": "IT",
        "entra_tenant_id": None,
        "entra_client_id": None,
        "budget_store_path": tmp_path / "budgets.json",
        "budget_notification_targets": (
            "ops-center=NOTIFICATION_CENTER",
            "ops-teams=TEAMS",
            "ops-email=EMAIL",
        ),
        "teams_webhook_url": "https://webhook.example.com/teams",
        "default_personal_daily_budget_enabled": True,
        "default_personal_daily_budget_threshold": 50.0,
        "default_personal_daily_warning_threshold": 40.0,
        "budget_eval_interval_seconds": 3600,
        **overrides,
    }
    return BackofficeSettings(**params)


def headers(role: str = "SYSTEM_ADMIN", user_id: str = "admin-1") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id,
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT",
        "X-Backoffice-Tenant-Id": "local-development",
    }


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


async def _seed_user_usage(
    store_path: Path,
    data_dir: Path,
    user_id: str,
    cost_usd: float,
    *,
    occurred_at: datetime | None = None,
) -> None:
    settings = _ops_settings(data_dir, store_path)
    ingestion = EventIngestionService(FileOperationalStore(store_path), settings)
    now = occurred_at or utc_now()
    turn_id = f"turn-{user_id}"
    events = [
        OperationalEvent(
            event_id=f"{turn_id}:turn.received",
            event_type="turn.received",
            occurred_at=now,
            conversation_id=f"conv-{user_id}",
            correlation_id=f"corr-{user_id}",
            turn_id=turn_id,
            actor_ref=user_id,
            payload={"messageMasked": "Question from user"},
        ),
        OperationalEvent(
            event_id=f"{turn_id}:usage.recorded",
            event_type="usage.recorded",
            occurred_at=now,
            conversation_id=f"conv-{user_id}",
            correlation_id=f"corr-{user_id}",
            turn_id=turn_id,
            actor_ref=user_id,
            payload={
                "component": "agent_service",
                "modelName": "gemini-2.5-flash",
                "inputTokens": 1000,
                "outputTokens": 500,
                "embeddingTokens": 0,
                "toolContextTokens": 0,
                "llmCallCount": 1,
                "estimatedCostUsd": cost_usd,
            },
        ),
    ]
    for ev in events:
        await ingestion.ingest(ev)


def test_calendar_day_alignment_today_preset() -> None:
    """REQ-023: Verify 'today' preset aligns to Asia/Taipei calendar day 00:00:00."""
    period = resolve_period(preset="today")
    now_taipei = utc_now().astimezone(ZoneInfo(DEFAULT_TIMEZONE))
    expected_start = now_taipei.replace(hour=0, minute=0, second=0, microsecond=0)

    assert period.days == 1
    assert period.preset == "today"
    assert period.explicit_range is True
    assert period.start_at == expected_start
    assert period.start_at.hour == 0
    assert period.start_at.minute == 0


@pytest.mark.asyncio
async def test_personal_daily_50_twd_auto_evaluation_and_alerts(tmp_path: Path) -> None:
    """REQ-023: Verify all users with usage today are evaluated against the 50 TWD daily policy."""
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = _settings(tmp_path)
    store_path = settings.ops_store_path

    # User Alice incurs 2.0 USD (~63.4 TWD > 50 TWD threshold)
    await _seed_user_usage(store_path, data_dir, "alice", cost_usd=2.0)
    # User Bob incurs 0.5 USD (~15.85 TWD < 40 TWD warning threshold)
    await _seed_user_usage(store_path, data_dir, "bob", cost_usd=0.5)

    captured_posts = []

    def mock_transport_handler(request: httpx.Request) -> httpx.Response:
        captured_posts.append(request)
        return httpx.Response(200, json={"status": "delivered"})

    mock_transport = httpx.MockTransport(mock_transport_handler)
    sent_emails = []

    def mock_email_sender(to: str, subject: str, body: str) -> None:
        sent_emails.append((to, subject, body))

    app = create_app(
        settings,
        notification_transport=mock_transport,
        email_sender=mock_email_sender,
    )
    client = TestClient(app)

    # Trigger evaluate-all endpoint
    eval_resp = client.post("/api/budget-policies/evaluate-all", headers=headers())
    assert eval_resp.status_code == 200
    data = eval_resp.json()
    assert data["evaluatedUsers"] >= 2
    assert data["triggeredAlerts"] >= 1

    # Verify Alice's policy was auto-provisioned with 50 TWD threshold
    policies_resp = client.get("/api/budget-policies", headers=headers())
    assert policies_resp.status_code == 200
    alice_policy = next(
        p for p in policies_resp.json()["items"]
        if p["scope_type"] == "PERSONAL" and p["scope_id"] == "alice"
    )
    assert alice_policy["period"] == "DAILY"
    assert alice_policy["measure"] == "TWD"
    assert alice_policy["warning_threshold"] == 40.0
    assert alice_policy["critical_threshold"] == 50.0

    # Verify Alice's critical alert was generated
    alerts_resp = client.get("/api/alerts?scope_id=alice", headers=headers())
    assert alerts_resp.status_code == 200
    alice_alerts = alerts_resp.json()["items"]
    assert len(alice_alerts) == 1
    assert alice_alerts[0]["severity"] == "CRITICAL"
    assert alice_alerts[0]["actual_value"] > 50.0

    # Verify external notifications were truly sent to Teams and Email
    deliveries = alice_alerts[0]["deliveries"]
    status_by_channel = {d["channel"]: d["status"] for d in deliveries}
    assert status_by_channel["NOTIFICATION_CENTER"] == "SENT"
    assert status_by_channel["TEAMS"] == "SENT"
    assert status_by_channel["EMAIL"] == "SENT"

    assert len(captured_posts) >= 1
    assert len(sent_emails) >= 1


@pytest.mark.asyncio
async def test_sync_failure_operational_alert_and_delivery(tmp_path: Path) -> None:
    """REQ-025: Verify knowledge sync failure triggers SYNC_FAILURE operational alert and external notification."""
    settings = _settings(tmp_path, sync_adapter_url="")  # empty adapter URL causes immediate failure
    dispatched_teams = []

    def mock_transport_handler(request: httpx.Request) -> httpx.Response:
        dispatched_teams.append(request)
        return httpx.Response(200, json={"ok": True})

    app = create_app(
        settings,
        notification_transport=httpx.MockTransport(mock_transport_handler),
    )
    client = TestClient(app)

    # Request a sync job
    sync_resp = client.post(
        "/api/sync-jobs",
        json={"scope_type": "ALL", "reason": "Monthly knowledge refresh"},
        headers=headers(),
    )
    assert sync_resp.status_code == 200
    job_id = sync_resp.json()["job"]["job_id"]

    # In test client / background task, sync job fails because adapter is not configured
    # Verify sync failure alert was generated
    alerts_resp = client.get("/api/alerts?alert_type=SYNC_FAILURE", headers=headers())
    assert alerts_resp.status_code == 200
    sync_alerts = alerts_resp.json()["items"]
    assert len(sync_alerts) == 1
    assert sync_alerts[0]["alert_type"] == "SYNC_FAILURE"
    assert sync_alerts[0]["severity"] == "CRITICAL"
    assert sync_alerts[0]["scope_id"] == job_id
    assert "SYNC_ADAPTER_UNAVAILABLE" in sync_alerts[0]["message"]

    # Verify delivery to Teams was dispatched and marked SENT
    deliveries = sync_alerts[0]["deliveries"]
    teams_delivery = next(d for d in deliveries if d["channel"] == "TEAMS")
    assert teams_delivery["status"] == "SENT"
    assert teams_delivery["attempt_count"] == 1
    assert len(dispatched_teams) >= 1


@pytest.mark.asyncio
async def test_api_anomaly_alert_generation_and_acknowledgement(tmp_path: Path) -> None:
    """REQ-025: Verify API anomaly health check produces alert, and test acknowledge/resolve lifecycle."""
    settings = _settings(tmp_path, simulate_health_anomalies=True)
    app = create_app(settings)
    client = TestClient(app)

    # Check alerts via endpoint
    check_resp = client.post("/api/health/check-alerts", headers=headers())
    assert check_resp.status_code == 200
    data = check_resp.json()
    assert data["checked"] is True
    assert len(data["triggeredAlerts"]) > 0

    # Query alerts by alert_type=API_ANOMALY
    alerts_resp = client.get("/api/alerts?alert_type=API_ANOMALY", headers=headers())
    assert alerts_resp.status_code == 200
    items = alerts_resp.json()["items"]
    assert len(items) > 0

    target_alert = items[0]
    alert_id = target_alert["alert_id"]
    etag = target_alert["etag"]

    # Acknowledge the alert
    ack_resp = client.post(
        f"/api/alerts/{alert_id}/acknowledge",
        json={"expected_etag": etag, "reason": "SRE on call investigating"},
        headers=headers(),
    )
    assert ack_resp.status_code == 200
    ack_alert = ack_resp.json()["alert"]
    assert ack_alert["status"] == "ACKNOWLEDGED"

    # Resolve the alert
    resolve_resp = client.post(
        f"/api/alerts/{alert_id}/resolve",
        json={"expected_etag": ack_alert["etag"], "reason": "Incident resolved"},
        headers=headers(),
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["alert"]["status"] == "RESOLVED"


@pytest.mark.asyncio
async def test_delivery_retry_api_redelivery(tmp_path: Path) -> None:
    """REQ-025: Verify retry delivery API endpoint triggers immediate external dispatch."""
    settings = _settings(tmp_path, sync_adapter_url="")
    attempts = 0

    def mock_transport_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json={"status": "delivered"})

    app = create_app(
        settings,
        notification_transport=httpx.MockTransport(mock_transport_handler),
    )
    client = TestClient(app)

    # Trigger sync failure
    sync_resp = client.post(
        "/api/sync-jobs",
        json={"scope_type": "ALL", "reason": "Testing retry flow"},
        headers=headers(),
    )
    assert sync_resp.status_code == 200

    # Get the alert and failed Teams delivery
    alerts_resp = client.get("/api/alerts?alert_type=SYNC_FAILURE", headers=headers())
    alert = alerts_resp.json()["items"][0]
    alert_id = alert["alert_id"]
    failed_delivery = next(d for d in alert["deliveries"] if d["channel"] == "TEAMS")
    assert failed_delivery["status"] == "FAILED"
    delivery_id = failed_delivery["delivery_id"]

    # Call the retry endpoint
    retry_resp = client.post(
        f"/api/alerts/{alert_id}/deliveries/{delivery_id}/retry",
        headers=headers(),
    )
    assert retry_resp.status_code == 200
    retried = retry_resp.json()["delivery"]
    assert retried["status"] == "SENT"
    assert retried["attempt_count"] == 2
    assert attempts == 2

