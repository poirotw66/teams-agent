from pathlib import Path

import pytest

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.budget_domain import BudgetService, FileBudgetRepository
from ai_ops_backoffice.faq_domain.errors import FaqValidationError, FaqVersionConflictError

OWNER = ActorContext("owner", "Owner", "SERVICE_OWNER", ("IT",))
SYSTEM = ActorContext("system", "System", "SYSTEM_ADMIN", ())


def test_budget_alert_suppression_notification_and_resolution(tmp_path: Path) -> None:
    path = tmp_path / "budgets.json"
    service = BudgetService(
        FileBudgetRepository(path),
        notification_targets={"ops-center": "NOTIFICATION_CENTER"},
    )
    with pytest.raises(FaqValidationError, match="preconfigured"):
        service.create_policy(
            scope_type="PERSONAL", scope_id="user-1", period="DAILY", measure="TWD",
            warning_threshold=40, critical_threshold=50, owner_unit_id="IT",
            notification_target_ids=("external@example.com",), pricing_version="v1",
            exchange_rate_version="twd-v1", actor=OWNER,
        )
    policy = service.create_policy(
        scope_type="PERSONAL", scope_id="user-1", period="DAILY", measure="TWD",
        warning_threshold=40, critical_threshold=50, owner_unit_id="IT",
        notification_target_ids=("ops-center",), pricing_version="v1",
        exchange_rate_version="twd-v1", actor=OWNER,
    )["policy"]
    first = service.evaluate(
        policy["policy_id"], period_key="2026-09-03", actual_value=55,
        coverage=1, pricing_version="v1", exchange_rate_version="twd-v1", actor=SYSTEM,
    )["alert"]
    merged = service.evaluate(
        policy["policy_id"], period_key="2026-09-03", actual_value=60,
        coverage=1, pricing_version="v1", exchange_rate_version="twd-v1", actor=SYSTEM,
    )["alert"]
    assert merged["alert_id"] == first["alert_id"]
    alerts = service.list_alerts(actor=OWNER)
    assert len(alerts) == 1
    assert len(alerts[0]["deliveries"]) == 1
    assert alerts[0]["deliveries"][0]["status"] == "SENT"
    assert "user@example.com" not in alerts[0]["deliveries"][0]["summary"]
    acknowledged = service.change_alert(
        first["alert_id"], action="ACKNOWLEDGE", expected_etag=2,
        reason="investigating", actor=OWNER,
    )["alert"]
    with pytest.raises(FaqVersionConflictError):
        service.change_alert(
            first["alert_id"], action="RESOLVE", expected_etag=2,
            reason="stale", actor=OWNER,
        )
    resolved = service.change_alert(
        first["alert_id"], action="RESOLVE", expected_etag=acknowledged["etag"],
        reason="usage reviewed", actor=OWNER,
    )["alert"]
    assert resolved["status"] == "RESOLVED"
    restarted = BudgetService(
        FileBudgetRepository(path),
        notification_targets={"ops-center": "NOTIFICATION_CENTER"},
    )
    assert restarted.list_alerts(actor=OWNER)[0]["status"] == "RESOLVED"


def test_failed_external_notification_can_be_retried(tmp_path: Path) -> None:
    service = BudgetService(
        FileBudgetRepository(tmp_path / "budgets.json"),
        notification_targets={"ops-teams": "TEAMS"},
    )
    policy = service.create_policy(
        scope_type="TEAM", scope_id="team-1", period="MONTHLY", measure="USD",
        warning_threshold=10, critical_threshold=20, owner_unit_id="IT",
        notification_target_ids=("ops-teams",), pricing_version="v1",
        exchange_rate_version="twd-v1", actor=OWNER,
    )["policy"]
    alert = service.evaluate(
        policy["policy_id"], period_key="2026-09", actual_value=25, coverage=1,
        pricing_version="v1", exchange_rate_version="twd-v1", actor=SYSTEM,
    )["alert"]
    delivery = service.alert_detail(alert["alert_id"], actor=OWNER)["deliveries"][0]
    assert delivery["status"] == "PENDING"
    failed = service.record_delivery_attempt(
        delivery["delivery_id"], success=False, error="provider user@example.com failed",
        actor=SYSTEM,
    )["delivery"]
    assert failed["status"] == "FAILED"
    assert "user@example.com" not in failed["last_error"]
    retried = service.retry_delivery(delivery["delivery_id"], actor=OWNER)["delivery"]
    assert retried["status"] == "PENDING"
    assert retried["attempt_count"] == 1


def test_operational_alerts_sync_and_api_anomaly(tmp_path: Path) -> None:
    service = BudgetService(
        FileBudgetRepository(tmp_path / "budgets.json"),
        notification_targets={"ops-center": "NOTIFICATION_CENTER", "ops-teams": "TEAMS"},
    )
    # 1. Trigger SYNC_FAILURE alert
    sync_alert = service.trigger_operational_alert(
        alert_type="SYNC_FAILURE",
        severity="CRITICAL",
        scope_type="SYNC_JOB",
        scope_id="job-123",
        period_key="2026-09-07",
        owner_unit_id="IT",
        summary="Knowledge sync failed for ALL: adapter unreachable",
        actor=SYSTEM,
    )["alert"]
    assert sync_alert["alert_type"] == "SYNC_FAILURE"
    assert sync_alert["severity"] == "CRITICAL"
    assert sync_alert["scope_id"] == "job-123"

    # Verify deliveries: in-app is SENT, external is PENDING
    detail = service.alert_detail(sync_alert["alert_id"], actor=OWNER)
    deliveries = {d["channel"]: d["status"] for d in detail["deliveries"]}
    assert deliveries["NOTIFICATION_CENTER"] == "SENT"
    assert deliveries["TEAMS"] == "PENDING"

    # 2. Trigger API_ANOMALY alert
    api_alert = service.trigger_operational_alert(
        alert_type="API_ANOMALY",
        severity="WARNING",
        scope_type="SERVICE",
        scope_id="agent-service",
        period_key="2026-09-07",
        owner_unit_id="IT",
        summary="API anomaly in agent-service: status=DEGRADED, errorRate=8%",
        actor=SYSTEM,
        threshold=0.05,
        actual_value=0.08,
    )["alert"]
    assert api_alert["alert_type"] == "API_ANOMALY"
    assert api_alert["severity"] == "WARNING"

    # 3. Test filtering
    sync_only = service.list_alerts(actor=OWNER, alert_type="SYNC_FAILURE")
    assert len(sync_only) == 1
    assert sync_only[0]["alert_type"] == "SYNC_FAILURE"

    critical_only = service.list_alerts(actor=OWNER, severity="CRITICAL")
    assert len(critical_only) == 1
    assert critical_only[0]["alert_id"] == sync_alert["alert_id"]

    warning_only = service.list_alerts(actor=OWNER, severity="WARNING")
    assert len(warning_only) == 1
    assert warning_only[0]["alert_id"] == api_alert["alert_id"]


def test_ensure_personal_policy_auto_provisioning(tmp_path: Path) -> None:
    service = BudgetService(
        FileBudgetRepository(tmp_path / "budgets.json"),
        notification_targets={"ops-center": "NOTIFICATION_CENTER"},
    )
    # Auto-provision for user-42
    policy1 = service.ensure_personal_policy(
        user_id="user-42",
        warning_threshold=40.0,
        critical_threshold=50.0,
        pricing_version="v1",
        exchange_rate_version="twd-v1",
        actor=SYSTEM,
    )
    assert policy1["scope_type"] == "PERSONAL"
    assert policy1["scope_id"] == "user-42"
    assert policy1["period"] == "DAILY"
    assert policy1["measure"] == "TWD"
    assert policy1["critical_threshold"] == 50.0
    assert policy1["warning_threshold"] == 40.0

    # Ensure idempotence: subsequent calls return existing policy
    policy2 = service.ensure_personal_policy(
        user_id="user-42",
        actor=SYSTEM,
    )
    assert policy2["policy_id"] == policy1["policy_id"]


@pytest.mark.asyncio
async def test_notification_dispatcher_teams_and_email(tmp_path: Path) -> None:
    import httpx
    from ai_ops_backoffice.notification_dispatcher import NotificationDispatcher
    from ai_ops_backoffice.settings import BackofficeSettings

    service = BudgetService(
        FileBudgetRepository(tmp_path / "budgets.json"),
        notification_targets={"ops-teams": "TEAMS", "ops-email": "EMAIL"},
    )
    alert = service.trigger_operational_alert(
        alert_type="SYNC_FAILURE",
        severity="CRITICAL",
        scope_type="SYNC_JOB",
        scope_id="job-404",
        period_key="2026-09-07",
        owner_unit_id="IT",
        summary="Knowledge sync failed: connection refused",
        actor=SYSTEM,
    )["alert"]

    deliveries = service.alert_detail(alert["alert_id"], actor=OWNER)["deliveries"]
    teams_delivery = next(d for d in deliveries if d["channel"] == "TEAMS")
    email_delivery = next(d for d in deliveries if d["channel"] == "EMAIL")

    # 1. Teams dispatch with successful HTTP 200
    captured_requests = []

    def mock_transport_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    from dataclasses import replace

    transport = httpx.MockTransport(mock_transport_handler)
    settings = replace(
        BackofficeSettings.from_env(),
        teams_webhook_url="https://example.com/teams/webhook",
        environment="test",
    )
    # 1. Teams dispatch failure with HTTP 500
    def failing_transport_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    failing_transport = httpx.MockTransport(failing_transport_handler)
    dispatcher_fail = NotificationDispatcher(settings, service, http_transport=failing_transport)

    res_fail = await dispatcher_fail.dispatch_delivery(teams_delivery, actor=SYSTEM)
    assert res_fail["delivery"]["status"] == "FAILED"
    assert "HTTP 500" in res_fail["delivery"]["last_error"]
    assert res_fail["delivery"]["attempt_count"] == 1

    # 2. Retry delivery to make it PENDING again, then dispatch successfully with HTTP 200
    service.retry_delivery(teams_delivery["delivery_id"], actor=OWNER)
    retried_delivery = service.alert_detail(alert["alert_id"], actor=OWNER)["deliveries"][0]
    assert retried_delivery["status"] == "PENDING"

    dispatcher = NotificationDispatcher(settings, service, http_transport=transport)
    res = await dispatcher.dispatch_delivery(retried_delivery, actor=SYSTEM)
    assert res["delivery"]["status"] == "SENT"
    assert res["delivery"]["attempt_count"] == 2
    assert len(captured_requests) == 1
    assert captured_requests[0].url == "https://example.com/teams/webhook"

    # 3. Email dispatch with custom email sender
    sent_emails = []

    def test_email_sender(to: str, subject: str, body: str) -> None:
        sent_emails.append((to, subject, body))

    dispatcher_email = NotificationDispatcher(settings, service, email_sender=test_email_sender)
    res_email = await dispatcher_email.dispatch_delivery(email_delivery, actor=SYSTEM)
    assert res_email["delivery"]["status"] == "SENT"
    assert len(sent_emails) == 1
    assert "Knowledge sync failed" in sent_emails[0][1]