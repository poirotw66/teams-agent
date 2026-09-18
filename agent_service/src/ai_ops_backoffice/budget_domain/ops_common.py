"""Shared authorization, audit, and notification helpers for budget ops."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from operations_core.access import ActorContext
from operations_core.masking import mask_text

from ..faq_domain.errors import FaqAuthorizationError
from .models import AlertEvent, BudgetAuditEvent, NotificationDelivery

__all__ = [
    "authorize",
    "build_audit",
    "build_notification_deliveries",
    "find_open_alert",
]


def authorize(actor: ActorContext, capability: str, owner_unit_id: str) -> None:
    if not actor.has_capability(capability) or not actor.allows_owner_unit(owner_unit_id):
        raise FaqAuthorizationError("budget operation is outside actor capability or scope")


def build_audit(
    target_type: Literal["BUDGET_POLICY", "ALERT"],
    target_id: str,
    action: str,
    actor: ActorContext,
    owner_unit_id: str,
    reason: str | None = None,
) -> BudgetAuditEvent:
    return BudgetAuditEvent(
        audit_id=str(uuid.uuid4()),
        target_type=target_type,
        target_id=target_id,
        action=action,
        actor_id=actor.user_id,
        actor_role=actor.role,
        owner_unit_id=owner_unit_id,
        reason=mask_text(reason).text if reason else None,
        occurred_at=datetime.now(UTC),
    )


def find_open_alert(
    alerts: tuple[AlertEvent, ...],
    *,
    suppression_key: str,
) -> AlertEvent | None:
    return next(
        (
            item
            for item in alerts
            if item.suppression_key == suppression_key and item.status != "RESOLVED"
        ),
        None,
    )


def build_notification_deliveries(
    *,
    alert_id: str,
    target_ids: tuple[str, ...],
    notification_targets: dict[str, str],
    summary: str,
    now: datetime,
) -> tuple[NotificationDelivery, ...]:
    deliveries: list[NotificationDelivery] = []
    for target_id in target_ids:
        if target_id not in notification_targets:
            continue
        channel = notification_targets[target_id]
        is_center = channel == "NOTIFICATION_CENTER"
        deliveries.append(
            NotificationDelivery(
                delivery_id=str(uuid.uuid4()),
                alert_id=alert_id,
                target_id=target_id,
                channel=channel,
                status="SENT" if is_center else "PENDING",
                summary=summary,
                attempt_count=1 if is_center else 0,
                created_at=now,
                updated_at=now,
            )
        )
    return tuple(deliveries)
