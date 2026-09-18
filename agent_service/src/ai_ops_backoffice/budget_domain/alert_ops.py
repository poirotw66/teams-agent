"""Budget spend evaluation and alert lifecycle use-case helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from operations_core.access import ActorContext
from operations_core.masking import mask_text

from ..faq_domain.errors import (
    FaqNotFoundError,
    FaqTransitionError,
    FaqVersionConflictError,
)
from .models import AlertEvent, BudgetPolicy, BudgetState
from .ops_common import (
    authorize,
    build_audit,
    build_notification_deliveries,
    find_open_alert,
)
from .repository import BudgetRepository

__all__ = [
    "alert_detail",
    "change_alert",
    "evaluate",
    "list_alerts",
    "trigger_operational_alert",
]


def _severity_for_value(policy: BudgetPolicy, actual_value: float) -> str | None:
    if actual_value >= policy.critical_threshold:
        return "CRITICAL"
    if actual_value >= policy.warning_threshold:
        return "WARNING"
    return None


def _merge_open_alert(
    current: AlertEvent,
    *,
    severity: str,
    threshold: float,
    actual_value: float,
    coverage: float,
    pricing_version: str,
    exchange_rate_version: str,
    message: str | None,
    now: datetime,
) -> AlertEvent:
    updates: dict[str, Any] = {
        "severity": severity,
        "threshold": threshold,
        "actual_value": actual_value,
        "coverage": coverage,
        "pricing_version": pricing_version,
        "exchange_rate_version": exchange_rate_version,
        "last_triggered_at": now,
        "etag": current.etag + 1,
    }
    if message is not None:
        updates["message"] = message
    return current.model_copy(update=updates)


def _create_threshold_alert(
    policy: BudgetPolicy,
    *,
    policy_id: str,
    period_key: str,
    suppression_key: str,
    severity: str,
    threshold: float,
    actual_value: float,
    coverage: float,
    pricing_version: str,
    exchange_rate_version: str,
    notification_targets: dict[str, str],
    now: datetime,
) -> tuple[AlertEvent, tuple]:
    alert = AlertEvent(
        alert_id=str(uuid.uuid4()),
        policy_id=policy_id,
        severity=severity,
        scope_type=policy.scope_type,
        scope_id=policy.scope_id,
        period_key=period_key,
        suppression_key=suppression_key,
        threshold=threshold,
        actual_value=actual_value,
        coverage=coverage,
        pricing_version=pricing_version,
        exchange_rate_version=exchange_rate_version,
        owner_unit_id=policy.owner_unit_id,
        first_triggered_at=now,
        last_triggered_at=now,
    )
    summary = (
        f"{severity} budget alert for {policy.scope_type}:{policy.scope_id}; "
        f"actual={actual_value:.4f}, threshold={threshold:.4f}"
    )
    new_deliveries = build_notification_deliveries(
        alert_id=alert.alert_id,
        target_ids=policy.notification_target_ids,
        notification_targets=notification_targets,
        summary=summary,
        now=now,
    )
    return alert, new_deliveries


def _apply_threshold_evaluation(
    state: BudgetState,
    *,
    policy_id: str,
    period_key: str,
    actual_value: float,
    coverage: float,
    pricing_version: str,
    exchange_rate_version: str,
    notification_targets: dict[str, str],
    actor: ActorContext,
) -> tuple[BudgetState, dict[str, Any]]:
    policy = next((item for item in state.policies if item.policy_id == policy_id), None)
    if policy is None:
        raise FaqNotFoundError(policy_id)
    authorize(actor, "ops.budget.evaluate", policy.owner_unit_id)
    if not policy.enabled:
        raise FaqTransitionError("disabled budget policies cannot be evaluated")
    severity = _severity_for_value(policy, actual_value)
    if severity is None:
        return state.model_copy(update={"revision": state.revision + 1}), {
            "alert": None,
            "triggered": False,
        }
    threshold = (
        policy.critical_threshold if severity == "CRITICAL" else policy.warning_threshold
    )
    suppression_key = f"{policy_id}:{period_key}"
    current = find_open_alert(state.alerts, suppression_key=suppression_key)
    now = datetime.now(UTC)
    if current:
        alert = _merge_open_alert(
            current,
            severity=severity,
            threshold=threshold,
            actual_value=actual_value,
            coverage=coverage,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            message=None,
            now=now,
        )
        alerts = tuple(alert if item.alert_id == alert.alert_id else item for item in state.alerts)
        deliveries = state.deliveries
        action = "ALERT_MERGED"
    else:
        alert, new_deliveries = _create_threshold_alert(
            policy,
            policy_id=policy_id,
            period_key=period_key,
            suppression_key=suppression_key,
            severity=severity,
            threshold=threshold,
            actual_value=actual_value,
            coverage=coverage,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            notification_targets=notification_targets,
            now=now,
        )
        alerts = (*state.alerts, alert)
        deliveries = (*state.deliveries, *new_deliveries)
        action = "ALERT_TRIGGERED"
    audit = build_audit("ALERT", alert.alert_id, action, actor, policy.owner_unit_id)
    return BudgetState(
        revision=state.revision + 1,
        policies=state.policies,
        alerts=alerts,
        deliveries=deliveries,
        audits=(*state.audits, audit),
    ), {"alert": alert.model_dump(mode="json"), "triggered": True}


def evaluate(
    repository: BudgetRepository,
    notification_targets: dict[str, str],
    policy_id: str,
    *,
    period_key: str,
    actual_value: float,
    coverage: float,
    pricing_version: str,
    exchange_rate_version: str,
    actor: ActorContext,
) -> dict[str, Any]:
    def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
        return _apply_threshold_evaluation(
            state,
            policy_id=policy_id,
            period_key=period_key,
            actual_value=actual_value,
            coverage=coverage,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            notification_targets=notification_targets,
            actor=actor,
        )

    return repository.mutate(operation)


def _apply_operational_alert(
    state: BudgetState,
    *,
    alert_type: Literal["SYNC_FAILURE", "API_ANOMALY"],
    severity: Literal["WARNING", "CRITICAL"],
    scope_type: str,
    scope_id: str,
    period_key: str,
    owner_unit_id: str,
    summary: str,
    actor: ActorContext,
    target_ids: tuple[str, ...],
    notification_targets: dict[str, str],
    threshold: float,
    actual_value: float,
    coverage: float,
    pricing_version: str,
    exchange_rate_version: str,
) -> tuple[BudgetState, dict[str, Any]]:
    suppression_key = f"{alert_type}:{scope_type}:{scope_id}:{period_key}"
    current = find_open_alert(state.alerts, suppression_key=suppression_key)
    now = datetime.now(UTC)
    masked_summary = mask_text(summary).text
    if current:
        alert = _merge_open_alert(
            current,
            severity=severity,
            threshold=threshold,
            actual_value=actual_value,
            coverage=coverage,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            message=masked_summary,
            now=now,
        )
        alerts = tuple(alert if item.alert_id == alert.alert_id else item for item in state.alerts)
        deliveries = state.deliveries
        action = "OPERATIONAL_ALERT_MERGED"
    else:
        alert = AlertEvent(
            alert_id=str(uuid.uuid4()),
            policy_id=f"op:{alert_type.lower()}:{scope_id}",
            alert_type=alert_type,
            severity=severity,
            scope_type=scope_type,
            scope_id=scope_id,
            period_key=period_key,
            suppression_key=suppression_key,
            threshold=threshold,
            actual_value=actual_value,
            coverage=coverage,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            owner_unit_id=owner_unit_id,
            message=masked_summary,
            first_triggered_at=now,
            last_triggered_at=now,
        )
        alerts = (*state.alerts, alert)
        deliveries = (
            *state.deliveries,
            *build_notification_deliveries(
                alert_id=alert.alert_id,
                target_ids=target_ids,
                notification_targets=notification_targets,
                summary=masked_summary,
                now=now,
            ),
        )
        action = "OPERATIONAL_ALERT_TRIGGERED"
    audit = build_audit("ALERT", alert.alert_id, action, actor, owner_unit_id, summary)
    return BudgetState(
        revision=state.revision + 1,
        policies=state.policies,
        alerts=alerts,
        deliveries=deliveries,
        audits=(*state.audits, audit),
    ), {"alert": alert.model_dump(mode="json"), "triggered": True}


def trigger_operational_alert(
    repository: BudgetRepository,
    notification_targets: dict[str, str],
    *,
    alert_type: Literal["SYNC_FAILURE", "API_ANOMALY"],
    severity: Literal["WARNING", "CRITICAL"],
    scope_type: str,
    scope_id: str,
    period_key: str,
    owner_unit_id: str,
    summary: str,
    actor: ActorContext,
    notification_target_ids: tuple[str, ...] | None = None,
    threshold: float = 0.0,
    actual_value: float = 0.0,
    coverage: float = 1.0,
    pricing_version: str = "v1",
    exchange_rate_version: str = "v1",
) -> dict[str, Any]:
    authorize(actor, "ops.alerts.manage", owner_unit_id)
    target_ids = notification_target_ids or tuple(notification_targets.keys())

    def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
        return _apply_operational_alert(
            state,
            alert_type=alert_type,
            severity=severity,
            scope_type=scope_type,
            scope_id=scope_id,
            period_key=period_key,
            owner_unit_id=owner_unit_id,
            summary=summary,
            actor=actor,
            target_ids=target_ids,
            notification_targets=notification_targets,
            threshold=threshold,
            actual_value=actual_value,
            coverage=coverage,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
        )

    return repository.mutate(operation)


def list_alerts(
    repository: BudgetRepository,
    *,
    actor: ActorContext,
    alert_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    state = repository.load()
    results: list[dict[str, Any]] = []
    for item in reversed(state.alerts):
        if not actor.has_capability("ops.alerts.read") or not actor.allows_owner_unit(
            item.owner_unit_id
        ):
            continue
        if alert_type and item.alert_type != alert_type:
            continue
        if severity and item.severity != severity:
            continue
        if status and item.status != status:
            continue
        if scope_type and item.scope_type != scope_type:
            continue
        if scope_id and item.scope_id != scope_id:
            continue
        results.append(
            {
                **item.model_dump(mode="json"),
                "deliveries": [
                    delivery.model_dump(mode="json")
                    for delivery in state.deliveries
                    if delivery.alert_id == item.alert_id
                ],
            }
        )
    return results


def alert_detail(
    repository: BudgetRepository,
    alert_id: str,
    *,
    actor: ActorContext,
) -> dict[str, Any]:
    item = next(
        (alert for alert in list_alerts(repository, actor=actor) if alert["alert_id"] == alert_id),
        None,
    )
    if item is None:
        raise FaqNotFoundError(alert_id)
    return item


def change_alert(
    repository: BudgetRepository,
    alert_id: str,
    *,
    action: Literal["ACKNOWLEDGE", "RESOLVE"],
    expected_etag: int,
    reason: str,
    actor: ActorContext,
) -> dict[str, Any]:
    def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
        current = next((item for item in state.alerts if item.alert_id == alert_id), None)
        if current is None:
            raise FaqNotFoundError(alert_id)
        authorize(actor, "ops.alerts.manage", current.owner_unit_id)
        if current.etag != expected_etag:
            raise FaqVersionConflictError("alert was changed by another request")
        if action == "ACKNOWLEDGE" and current.status != "OPEN":
            raise FaqTransitionError("only open alerts can be acknowledged")
        if action == "RESOLVE" and current.status not in {"OPEN", "ACKNOWLEDGED"}:
            raise FaqTransitionError("alert is already resolved")
        now = datetime.now(UTC)
        updates: dict[str, Any] = {
            "status": "ACKNOWLEDGED" if action == "ACKNOWLEDGE" else "RESOLVED",
            "etag": current.etag + 1,
        }
        if action == "ACKNOWLEDGE":
            updates.update({"acknowledged_by": actor.user_id, "acknowledged_at": now})
        else:
            updates.update(
                {
                    "resolved_by": actor.user_id,
                    "resolved_at": now,
                    "resolution_note": mask_text(reason).text,
                }
            )
        updated = current.model_copy(update=updates)
        alerts = tuple(updated if item.alert_id == alert_id else item for item in state.alerts)
        audit = build_audit(
            "ALERT", alert_id, f"ALERT_{action}D", actor, current.owner_unit_id, reason
        )
        return BudgetState(
            revision=state.revision + 1,
            policies=state.policies,
            alerts=alerts,
            deliveries=state.deliveries,
            audits=(*state.audits, audit),
        ), {"alert": updated.model_dump(mode="json")}

    return repository.mutate(operation)
