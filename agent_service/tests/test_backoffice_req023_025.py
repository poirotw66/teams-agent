from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest
import httpx

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.budget_domain import (
    AlertEvent,
    BudgetPolicy,
    BudgetService,
    FileBudgetRepository,
    NotificationDelivery,
)
from ai_ops_backoffice.notification_dispatcher import NotificationDispatcher
from ai_ops_backoffice.settings import BackofficeSettings

ADMIN = ActorContext("admin", "Admin", "SYSTEM_ADMIN", ())


def make_settings(tmp_path: Path, webhook_url: str | None = "https://example.com/webhook") -> BackofficeSettings:
    return BackofficeSettings(
        host="127.0.0.1",
        port=8080,
        service_token="test-token",
        auth_mode="HEADER",
        ops_store_mode="FILE",
        ops_store_path=tmp_path / "events.json",
        ops_taxonomy_path=tmp_path / "taxonomy.json",
        ops_metrics_path=tmp_path / "metrics.json",
        ops_classification_rules_path=tmp_path / "rules.json",
        ops_audit_store_mode="FILE",
        knowledge_portal_url="https://portal.example.com",
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT",
        entra_tenant_id=None,
        entra_client_id=None,
        teams_webhook_url=webhook_url,
    )


@pytest.mark.asyncio
async def test_req025_notification_dispatcher_attaches_reason_and_backoffice_deep_link(tmp_path: Path) -> None:
    """Verify alert notifications attach identifiable error reason and backoffice deep-link context."""
    budget_path = tmp_path / "budgets.json"
    repo = FileBudgetRepository(budget_path)
    service = BudgetService(repo, notification_targets={"teams-target": "https://example.com/webhook"})

    now = datetime.now(UTC)

    # 1. Create a SYNC_FAILURE alert
    sync_alert = AlertEvent(
        alert_id="alt-sync-001",
        policy_id=None,
        alert_type="SYNC_FAILURE",
        severity="CRITICAL",
        scope_type="SYNC_JOB",
        scope_id="job-sync-888",
        period_key=now.strftime("%Y-%m-%d"),
        suppression_key="sync:job-sync-888",
        owner_unit_id="IT",
        first_triggered_at=now,
        last_triggered_at=now,
        message="Knowledge sync failed due to Azure Search indexer timeout",
    )

    delivery = NotificationDelivery(
        delivery_id="del-teams-001",
        alert_id="alt-sync-001",
        target_id="https://example.com/webhook",
        channel="TEAMS",
        status="PENDING",
        summary="Knowledge sync failed for job-sync-888",
        created_at=now,
        updated_at=now,
    )

    # Save to budget state
    def add_alert_op(state):
        return state.model_copy(update={
            "revision": state.revision + 1,
            "alerts": (sync_alert,),
            "deliveries": (delivery,),
        }), {}
    repo.mutate(add_alert_op)

    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured_requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    settings = make_settings(tmp_path, webhook_url="https://example.com/webhook")
    dispatcher = NotificationDispatcher(settings, service, http_transport=transport)

    result = await dispatcher.dispatch_delivery(delivery, actor=ADMIN)
    assert result["delivery"]["status"] == "SENT"
    assert len(captured_requests) == 1

    card = captured_requests[0]
    adaptive_card = card["attachments"][0]["content"]
    facts = adaptive_card["body"][2]["facts"]
    fact_dict = {f["title"]: f["value"] for f in facts}

    assert "Reason" in fact_dict
    assert "Azure Search indexer timeout" in fact_dict["Reason"]
    assert "Context" in fact_dict
    assert "同步管理" in fact_dict["Context"]
    assert "Deep Link" in fact_dict
    assert "jobId=job-sync-888" in fact_dict["Deep Link"]

    action = adaptive_card["actions"][0]
    assert action["type"] == "Action.OpenUrl"
    assert "jobId=job-sync-888" in action["url"]


@pytest.mark.asyncio
async def test_req025_email_notification_dispatcher_attaches_reason_and_deep_link(tmp_path: Path) -> None:
    """Verify email notifications attach identifiable reason and backoffice deep-link context."""
    budget_path = tmp_path / "budgets.json"
    repo = FileBudgetRepository(budget_path)
    service = BudgetService(repo, notification_targets={"email-target": "ops@example.com"})

    now = datetime.now(UTC)

    budget_alert = AlertEvent(
        alert_id="alt-budget-002",
        policy_id="pol-model-gpt4",
        alert_type="BUDGET_THRESHOLD",
        severity="WARNING",
        scope_type="MODEL",
        scope_id="gpt-4o",
        period_key=now.strftime("%Y-%m-%d"),
        suppression_key="budget:gpt-4o",
        owner_unit_id="IT",
        first_triggered_at=now,
        last_triggered_at=now,
        message="Model gpt-4o exceeded 85% daily token threshold",
    )

    delivery = NotificationDelivery(
        delivery_id="del-email-001",
        alert_id="alt-budget-002",
        target_id="ops@example.com",
        channel="EMAIL",
        status="PENDING",
        summary="Budget warning for model gpt-4o",
        created_at=now,
        updated_at=now,
    )

    def add_alert_op(state):
        return state.model_copy(update={
            "revision": state.revision + 1,
            "alerts": (budget_alert,),
            "deliveries": (delivery,),
        }), {}
    repo.mutate(add_alert_op)

    captured_emails = []

    def mock_email_sender(to_addr: str, subject: str, body: str) -> None:
        captured_emails.append({"to": to_addr, "subject": subject, "body": body})

    settings = make_settings(tmp_path)
    dispatcher = NotificationDispatcher(settings, service, email_sender=mock_email_sender)

    result = await dispatcher.dispatch_delivery(delivery, actor=ADMIN)
    assert result["delivery"]["status"] == "SENT"
    assert len(captured_emails) == 1

    email = captured_emails[0]
    assert email["to"] == "ops@example.com"
    assert "gpt-4o" in email["subject"]
    assert "Reason: Model gpt-4o exceeded 85% daily token threshold" in email["body"]
    assert "Context: Cost & Budget / 預算管理" in email["body"]
    assert "budgets?alertId=alt-budget-002" in email["body"]


def test_req023_budget_service_retention_and_purge(tmp_path: Path) -> None:
    """Verify budget alerts, deliveries, and expired policies are purged past 365 days retention."""
    budget_path = tmp_path / "budgets.json"
    repo = FileBudgetRepository(budget_path)
    service = BudgetService(repo, notification_targets={})

    now = datetime.now(UTC)
    old_time = now - timedelta(days=400)
    recent_time = now - timedelta(days=30)

    # 1. Expired resolved alert (>365d)
    expired_alert = AlertEvent(
        alert_id="alt-expired-001",
        policy_id=None,
        alert_type="BUDGET_THRESHOLD",
        severity="WARNING",
        scope_type="GLOBAL",
        scope_id="all",
        period_key=old_time.strftime("%Y-%m-%d"),
        suppression_key="old-key",
        owner_unit_id="IT",
        status="RESOLVED",
        first_triggered_at=old_time,
        last_triggered_at=old_time,
        resolved_at=old_time,
        resolved_by="admin",
        resolution_note="Old resolved issue",
    )

    # 2. Active recent alert
    active_alert = AlertEvent(
        alert_id="alt-active-002",
        policy_id=None,
        alert_type="BUDGET_THRESHOLD",
        severity="CRITICAL",
        scope_type="MODEL",
        scope_id="gpt-4o",
        period_key=recent_time.strftime("%Y-%m-%d"),
        suppression_key="recent-key",
        owner_unit_id="IT",
        status="OPEN",
        first_triggered_at=recent_time,
        last_triggered_at=recent_time,
    )

    # 3. Expired delivery (>365d)
    expired_delivery = NotificationDelivery(
        delivery_id="del-expired-001",
        alert_id="alt-expired-001",
        target_id="ops@example.com",
        channel="EMAIL",
        status="SENT",
        summary="Old sent delivery",
        created_at=old_time,
        updated_at=old_time,
    )

    # 4. Recent delivery
    recent_delivery = NotificationDelivery(
        delivery_id="del-recent-002",
        alert_id="alt-active-002",
        target_id="ops@example.com",
        channel="EMAIL",
        status="SENT",
        summary="Recent sent delivery",
        created_at=recent_time,
        updated_at=recent_time,
    )

    # 5. Active policy (should never be purged)
    active_policy = BudgetPolicy(
        policy_id="pol-active-001",
        scope_type="MODEL",
        scope_id="gpt-4o",
        period="DAILY",
        measure="TWD",
        warning_threshold=500.0,
        critical_threshold=1000.0,
        enabled=True,
        effective_at=recent_time,
        expires_at=None,
        owner_unit_id="IT",
        notification_target_ids=(),
        pricing_version="v1",
        exchange_rate_version="v1",
        created_by="admin",
        created_at=recent_time,
        updated_by="admin",
        updated_at=recent_time,
    )

    def seed_op(state):
        return state.model_copy(update={
            "revision": state.revision + 1,
            "policies": (active_policy,),
            "alerts": (expired_alert, active_alert),
            "deliveries": (expired_delivery, recent_delivery),
        }), {}
    repo.mutate(seed_op)

    # Run purge
    purge_result = service.purge_expired(retention_days=365, actor=ADMIN, now=now)
    assert purge_result["total"] >= 2
    assert purge_result["purged_alerts"] == 1
    assert purge_result["purged_deliveries"] == 1

    # Verify state after purge
    state = repo.load()
    alert_ids = [a.alert_id for a in state.alerts]
    delivery_ids = [d.delivery_id for d in state.deliveries]
    policy_ids = [p.policy_id for p in state.policies]

    assert "alt-expired-001" not in alert_ids
    assert "alt-active-002" in alert_ids
    assert "del-expired-001" not in delivery_ids
    assert "del-recent-002" in delivery_ids
    assert "pol-active-001" in policy_ids
