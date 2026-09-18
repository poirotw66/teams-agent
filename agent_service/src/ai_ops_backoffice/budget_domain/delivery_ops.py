"""Notification delivery and retention purge use-case helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from operations_core.access import ActorContext
from operations_core.masking import mask_text

from ..faq_domain.errors import FaqNotFoundError, FaqTransitionError
from .models import BudgetAuditEvent, BudgetState
from .ops_common import authorize, build_audit
from .repository import BudgetRepository

__all__ = [
    "purge_expired",
    "record_delivery_attempt",
    "retry_delivery",
]


def record_delivery_attempt(
    repository: BudgetRepository,
    delivery_id: str,
    *,
    success: bool,
    error: str | None,
    actor: ActorContext,
) -> dict[str, Any]:
    def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
        current = next(
            (item for item in state.deliveries if item.delivery_id == delivery_id),
            None,
        )
        if current is None:
            raise FaqNotFoundError(delivery_id)
        alert = next(item for item in state.alerts if item.alert_id == current.alert_id)
        authorize(actor, "ops.alerts.manage", alert.owner_unit_id)
        now = datetime.now(UTC)
        updated = current.model_copy(
            update={
                "status": "SENT" if success else "FAILED",
                "attempt_count": current.attempt_count + 1,
                "last_error": mask_text(error).text if error and not success else None,
                "updated_at": now,
            }
        )
        deliveries = tuple(
            updated if item.delivery_id == delivery_id else item for item in state.deliveries
        )
        action = "NOTIFICATION_SENT" if success else "NOTIFICATION_FAILED"
        audit = build_audit("ALERT", alert.alert_id, action, actor, alert.owner_unit_id, error)
        return BudgetState(
            revision=state.revision + 1,
            policies=state.policies,
            alerts=state.alerts,
            deliveries=deliveries,
            audits=(*state.audits, audit),
        ), {"delivery": updated.model_dump(mode="json")}

    return repository.mutate(operation)


def retry_delivery(
    repository: BudgetRepository,
    delivery_id: str,
    *,
    actor: ActorContext,
) -> dict[str, Any]:
    def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
        current = next(
            (item for item in state.deliveries if item.delivery_id == delivery_id),
            None,
        )
        if current is None:
            raise FaqNotFoundError(delivery_id)
        alert = next(item for item in state.alerts if item.alert_id == current.alert_id)
        authorize(actor, "ops.alerts.manage", alert.owner_unit_id)
        if current.status != "FAILED":
            raise FaqTransitionError("only failed notification deliveries can be retried")
        updated = current.model_copy(
            update={
                "status": "PENDING",
                "last_error": None,
                "updated_at": datetime.now(UTC),
            }
        )
        deliveries = tuple(
            updated if item.delivery_id == delivery_id else item for item in state.deliveries
        )
        audit = build_audit(
            "ALERT",
            alert.alert_id,
            "NOTIFICATION_RETRY_QUEUED",
            actor,
            alert.owner_unit_id,
        )
        return BudgetState(
            revision=state.revision + 1,
            policies=state.policies,
            alerts=state.alerts,
            deliveries=deliveries,
            audits=(*state.audits, audit),
        ), {"delivery": updated.model_dump(mode="json")}

    return repository.mutate(operation)


def _expired_ids(
    state: BudgetState,
    *,
    cutoff: datetime,
) -> tuple[set[str], set[str], set[str]]:
    expired_alert_ids = {
        alert.alert_id
        for alert in state.alerts
        if alert.status == "RESOLVED"
        and (alert.resolved_at or alert.last_triggered_at) < cutoff
    }
    expired_delivery_ids = {
        delivery.delivery_id
        for delivery in state.deliveries
        if (
            delivery.status in ("SENT", "FAILED")
            and (delivery.updated_at or delivery.created_at) < cutoff
        )
        or delivery.alert_id in expired_alert_ids
    }
    expired_policy_ids = {
        policy.policy_id
        for policy in state.policies
        if policy.expires_at is not None and policy.expires_at < cutoff
    }
    return expired_alert_ids, expired_delivery_ids, expired_policy_ids


def _purge_state(
    curr: BudgetState,
    *,
    expired_alert_ids: set[str],
    expired_delivery_ids: set[str],
    expired_policy_ids: set[str],
    retention_days: int,
    target_now: datetime,
    actor: ActorContext | None,
) -> tuple[BudgetState, dict[str, Any]]:
    kept_alerts = [alert for alert in curr.alerts if alert.alert_id not in expired_alert_ids]
    kept_deliveries = [
        delivery
        for delivery in curr.deliveries
        if delivery.delivery_id not in expired_delivery_ids
    ]
    kept_policies = [
        policy for policy in curr.policies if policy.policy_id not in expired_policy_ids
    ]
    purged_alerts_count = len(curr.alerts) - len(kept_alerts)
    purged_deliveries_count = len(curr.deliveries) - len(kept_deliveries)
    purged_policies_count = len(curr.policies) - len(kept_policies)
    total_purged = purged_alerts_count + purged_deliveries_count + purged_policies_count
    if total_purged == 0:
        return curr.model_copy(update={"revision": curr.revision + 1}), {
            "purged_alerts": 0,
            "purged_deliveries": 0,
            "purged_policies": 0,
            "total": 0,
        }
    audit = BudgetAuditEvent(
        audit_id=str(uuid.uuid4()),
        target_type="ALERT",
        target_id="RETENTION_PURGE",
        action="BUDGET_RETENTION_PURGED",
        actor_id=actor.user_id if actor else "system.retention",
        actor_role=actor.role if actor else "SYSTEM",
        owner_unit_id="ALL",
        reason=(
            f"Purged {total_purged} budget records (alerts: {purged_alerts_count}, "
            f"deliveries: {purged_deliveries_count}, policies: {purged_policies_count}) "
            f"past {retention_days} days retention."
        ),
        occurred_at=target_now,
    )
    next_state = BudgetState(
        revision=curr.revision + 1,
        policies=tuple(kept_policies),
        alerts=tuple(kept_alerts),
        deliveries=tuple(kept_deliveries),
        audits=(*curr.audits, audit),
    )
    return next_state, {
        "purged_alerts": purged_alerts_count,
        "purged_deliveries": purged_deliveries_count,
        "purged_policies": purged_policies_count,
        "total": total_purged,
    }


def purge_expired(
    repository: BudgetRepository,
    *,
    retention_days: int = 365,
    actor: ActorContext | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    target_now = now or datetime.now(UTC)
    cutoff = target_now - timedelta(days=retention_days)
    state = repository.load()
    expired_alert_ids, expired_delivery_ids, expired_policy_ids = _expired_ids(
        state, cutoff=cutoff
    )
    total = len(expired_alert_ids) + len(expired_delivery_ids) + len(expired_policy_ids)
    if total == 0:
        return {
            "purged_alerts": 0,
            "purged_deliveries": 0,
            "purged_policies": 0,
            "total": 0,
        }

    def operation(curr: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
        return _purge_state(
            curr,
            expired_alert_ids=expired_alert_ids,
            expired_delivery_ids=expired_delivery_ids,
            expired_policy_ids=expired_policy_ids,
            retention_days=retention_days,
            target_now=target_now,
            actor=actor,
        )

    return repository.mutate(operation)
