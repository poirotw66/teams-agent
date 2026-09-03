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