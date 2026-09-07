from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import mask_text

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)


from .models import *  # noqa: F403
from .repository import *  # noqa: F403

class BudgetService:
    def __init__(
        self,
        repository: BudgetRepository,
        *,
        notification_targets: dict[str, str],
    ) -> None:
        self._repository = repository
        self._notification_targets = notification_targets

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        if not actor.has_capability(capability) or not actor.allows_owner_unit(owner_unit_id):
            raise FaqAuthorizationError("budget operation is outside actor capability or scope")

    @staticmethod
    def _audit(
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

    def list_policies(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in self._repository.load().policies
            if actor.has_capability("ops.budget.read") and actor.allows_owner_unit(item.owner_unit_id)
        ]

    def policy_detail(self, policy_id: str, *, actor: ActorContext) -> dict[str, Any]:
        policy = next(
            (item for item in self._repository.load().policies if item.policy_id == policy_id),
            None,
        )
        if policy is None:
            raise FaqNotFoundError(policy_id)
        self._authorize(actor, "ops.budget.read", policy.owner_unit_id)
        return policy.model_dump(mode="json")

    def create_policy(
        self,
        *,
        scope_type: str,
        scope_id: str,
        period: str,
        measure: str,
        warning_threshold: float,
        critical_threshold: float,
        owner_unit_id: str,
        notification_target_ids: tuple[str, ...],
        pricing_version: str,
        exchange_rate_version: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._authorize(actor, "ops.budget.write", owner_unit_id)
        if warning_threshold >= critical_threshold:
            raise FaqValidationError("warning threshold must be lower than critical threshold")
        unknown = set(notification_target_ids) - self._notification_targets.keys()
        if unknown:
            raise FaqValidationError("notification targets must be preconfigured")
        now = datetime.now(UTC)
        policy = BudgetPolicy(
            policy_id=str(uuid.uuid4()),
            scope_type=scope_type,
            scope_id=scope_id,
            period=period,
            measure=measure,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            effective_at=now,
            owner_unit_id=owner_unit_id,
            notification_target_ids=notification_target_ids,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            created_by=actor.user_id,
            created_at=now,
            updated_by=actor.user_id,
            updated_at=now,
        )

        def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
            audit = self._audit(
                "BUDGET_POLICY", policy.policy_id, "BUDGET_POLICY_CREATED", actor, owner_unit_id
            )
            return BudgetState(
                revision=state.revision + 1,
                policies=(*state.policies, policy),
                alerts=state.alerts,
                deliveries=state.deliveries,
                audits=(*state.audits, audit),
            ), {"policy": policy.model_dump(mode="json")}

        return self._repository.mutate(operation)

    def set_policy_enabled(
        self,
        policy_id: str,
        *,
        enabled: bool,
        expected_etag: int,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
            current = next((item for item in state.policies if item.policy_id == policy_id), None)
            if current is None:
                raise FaqNotFoundError(policy_id)
            self._authorize(actor, "ops.budget.write", current.owner_unit_id)
            if current.etag != expected_etag:
                raise FaqVersionConflictError("budget policy was changed by another request")
            now = datetime.now(UTC)
            updated = current.model_copy(
                update={
                    "enabled": enabled,
                    "etag": current.etag + 1,
                    "updated_by": actor.user_id,
                    "updated_at": now,
                }
            )
            policies = tuple(updated if item.policy_id == policy_id else item for item in state.policies)
            action = "BUDGET_POLICY_ENABLED" if enabled else "BUDGET_POLICY_DISABLED"
            audit = self._audit("BUDGET_POLICY", policy_id, action, actor, current.owner_unit_id, reason)
            return BudgetState(
                revision=state.revision + 1,
                policies=policies,
                alerts=state.alerts,
                deliveries=state.deliveries,
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._repository.mutate(operation)

    def update_policy(
        self,
        policy_id: str,
        *,
        warning_threshold: float,
        critical_threshold: float,
        notification_target_ids: tuple[str, ...],
        expected_etag: int,
        actor: ActorContext,
    ) -> dict[str, Any]:
        if warning_threshold >= critical_threshold:
            raise FaqValidationError("warning threshold must be lower than critical threshold")
        if set(notification_target_ids) - self._notification_targets.keys():
            raise FaqValidationError("notification targets must be preconfigured")

        def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
            current = next((item for item in state.policies if item.policy_id == policy_id), None)
            if current is None:
                raise FaqNotFoundError(policy_id)
            self._authorize(actor, "ops.budget.write", current.owner_unit_id)
            if current.etag != expected_etag:
                raise FaqVersionConflictError("budget policy was changed by another request")
            updated = current.model_copy(
                update={
                    "warning_threshold": warning_threshold,
                    "critical_threshold": critical_threshold,
                    "notification_target_ids": notification_target_ids,
                    "etag": current.etag + 1,
                    "updated_by": actor.user_id,
                    "updated_at": datetime.now(UTC),
                }
            )
            policies = tuple(updated if item.policy_id == policy_id else item for item in state.policies)
            audit = self._audit(
                "BUDGET_POLICY",
                policy_id,
                "BUDGET_POLICY_UPDATED",
                actor,
                current.owner_unit_id,
            )
            return BudgetState(
                revision=state.revision + 1,
                policies=policies,
                alerts=state.alerts,
                deliveries=state.deliveries,
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._repository.mutate(operation)

    def evaluate(
        self,
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
            policy = next((item for item in state.policies if item.policy_id == policy_id), None)
            if policy is None:
                raise FaqNotFoundError(policy_id)
            self._authorize(actor, "ops.budget.evaluate", policy.owner_unit_id)
            if not policy.enabled:
                raise FaqTransitionError("disabled budget policies cannot be evaluated")
            severity = (
                "CRITICAL" if actual_value >= policy.critical_threshold
                else "WARNING" if actual_value >= policy.warning_threshold
                else None
            )
            if severity is None:
                return state.model_copy(update={"revision": state.revision + 1}), {
                    "alert": None,
                    "triggered": False,
                }
            threshold = (
                policy.critical_threshold if severity == "CRITICAL" else policy.warning_threshold
            )
            suppression_key = f"{policy_id}:{period_key}"
            current = next(
                (
                    item for item in state.alerts
                    if item.suppression_key == suppression_key and item.status != "RESOLVED"
                ),
                None,
            )
            now = datetime.now(UTC)
            if current:
                alert = current.model_copy(
                    update={
                        "severity": severity,
                        "threshold": threshold,
                        "actual_value": actual_value,
                        "coverage": coverage,
                        "pricing_version": pricing_version,
                        "exchange_rate_version": exchange_rate_version,
                        "last_triggered_at": now,
                        "etag": current.etag + 1,
                    }
                )
                alerts = tuple(alert if item.alert_id == alert.alert_id else item for item in state.alerts)
                deliveries = state.deliveries
                action = "ALERT_MERGED"
            else:
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
                alerts = (*state.alerts, alert)
                deliveries = (*state.deliveries, *(
                    NotificationDelivery(
                        delivery_id=str(uuid.uuid4()),
                        alert_id=alert.alert_id,
                        target_id=target_id,
                        channel=self._notification_targets[target_id],
                        status=(
                            "SENT"
                            if self._notification_targets[target_id] == "NOTIFICATION_CENTER"
                            else "PENDING"
                        ),
                        summary=(
                            f"{severity} budget alert for {policy.scope_type}:{policy.scope_id}; "
                            f"actual={actual_value:.4f}, threshold={threshold:.4f}"
                        ),
                        attempt_count=(
                            1
                            if self._notification_targets[target_id] == "NOTIFICATION_CENTER"
                            else 0
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                    for target_id in policy.notification_target_ids
                ))
                action = "ALERT_TRIGGERED"
            audit = self._audit("ALERT", alert.alert_id, action, actor, policy.owner_unit_id)
            return BudgetState(
                revision=state.revision + 1,
                policies=state.policies,
                alerts=alerts,
                deliveries=deliveries,
                audits=(*state.audits, audit),
            ), {"alert": alert.model_dump(mode="json"), "triggered": True}

        return self._repository.mutate(operation)

    def trigger_operational_alert(
        self,
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
        self._authorize(actor, "ops.alerts.manage", owner_unit_id)
        suppression_key = f"{alert_type}:{scope_type}:{scope_id}:{period_key}"
        target_ids = notification_target_ids or tuple(self._notification_targets.keys())

        def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
            current = next(
                (
                    item for item in state.alerts
                    if item.suppression_key == suppression_key and item.status != "RESOLVED"
                ),
                None,
            )
            now = datetime.now(UTC)
            if current:
                alert = current.model_copy(
                    update={
                        "severity": severity,
                        "threshold": threshold,
                        "actual_value": actual_value,
                        "coverage": coverage,
                        "pricing_version": pricing_version,
                        "exchange_rate_version": exchange_rate_version,
                        "message": mask_text(summary).text,
                        "last_triggered_at": now,
                        "etag": current.etag + 1,
                    }
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
                    message=mask_text(summary).text,
                    first_triggered_at=now,
                    last_triggered_at=now,
                )
                alerts = (*state.alerts, alert)
                deliveries = (*state.deliveries, *(
                    NotificationDelivery(
                        delivery_id=str(uuid.uuid4()),
                        alert_id=alert.alert_id,
                        target_id=target_id,
                        channel=self._notification_targets[target_id],
                        status=(
                            "SENT"
                            if self._notification_targets[target_id] == "NOTIFICATION_CENTER"
                            else "PENDING"
                        ),
                        summary=mask_text(summary).text,
                        attempt_count=(
                            1
                            if self._notification_targets[target_id] == "NOTIFICATION_CENTER"
                            else 0
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                    for target_id in target_ids
                    if target_id in self._notification_targets
                ))
                action = "OPERATIONAL_ALERT_TRIGGERED"
            audit = self._audit("ALERT", alert.alert_id, action, actor, owner_unit_id, summary)
            return BudgetState(
                revision=state.revision + 1,
                policies=state.policies,
                alerts=alerts,
                deliveries=deliveries,
                audits=(*state.audits, audit),
            ), {"alert": alert.model_dump(mode="json"), "triggered": True}

        return self._repository.mutate(operation)

    def ensure_personal_policy(
        self,
        user_id: str,
        *,
        owner_unit_id: str = "IT",
        warning_threshold: float = 40.0,
        critical_threshold: float = 50.0,
        notification_target_ids: tuple[str, ...] | None = None,
        pricing_version: str = "v1",
        exchange_rate_version: str = "twd-v1",
        actor: ActorContext,
    ) -> dict[str, Any]:
        state = self._repository.load()
        existing = next(
            (
                p for p in state.policies
                if p.scope_type == "PERSONAL" and p.scope_id == user_id and p.period == "DAILY" and p.measure == "TWD"
            ),
            None,
        )
        if existing:
            return existing.model_dump(mode="json")

        target_ids = notification_target_ids or tuple(self._notification_targets.keys())
        created = self.create_policy(
            scope_type="PERSONAL",
            scope_id=user_id,
            period="DAILY",
            measure="TWD",
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            owner_unit_id=owner_unit_id,
            notification_target_ids=target_ids,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            actor=actor,
        )
        return created["policy"]

    def list_alerts(
        self,
        *,
        actor: ActorContext,
        alert_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        state = self._repository.load()
        results: list[dict[str, Any]] = []
        for item in reversed(state.alerts):
            if not actor.has_capability("ops.alerts.read") or not actor.allows_owner_unit(item.owner_unit_id):
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
            results.append({
                **item.model_dump(mode="json"),
                "deliveries": [
                    delivery.model_dump(mode="json")
                    for delivery in state.deliveries
                    if delivery.alert_id == item.alert_id
                ],
            })
        return results

    def alert_detail(self, alert_id: str, *, actor: ActorContext) -> dict[str, Any]:
        item = next(
            (alert for alert in self.list_alerts(actor=actor) if alert["alert_id"] == alert_id),
            None,
        )
        if item is None:
            raise FaqNotFoundError(alert_id)
        return item

    def record_delivery_attempt(
        self,
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
            self._authorize(actor, "ops.alerts.manage", alert.owner_unit_id)
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
            audit = self._audit(
                "ALERT", alert.alert_id, action, actor, alert.owner_unit_id, error
            )
            return BudgetState(
                revision=state.revision + 1,
                policies=state.policies,
                alerts=state.alerts,
                deliveries=deliveries,
                audits=(*state.audits, audit),
            ), {"delivery": updated.model_dump(mode="json")}

        return self._repository.mutate(operation)

    def retry_delivery(
        self,
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
            self._authorize(actor, "ops.alerts.manage", alert.owner_unit_id)
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
            audit = self._audit(
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

        return self._repository.mutate(operation)

    def change_alert(
        self,
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
            self._authorize(actor, "ops.alerts.manage", current.owner_unit_id)
            if current.etag != expected_etag:
                raise FaqVersionConflictError("alert was changed by another request")
            if action == "ACKNOWLEDGE" and current.status != "OPEN":
                raise FaqTransitionError("only open alerts can be acknowledged")
            if action == "RESOLVE" and current.status not in {"OPEN", "ACKNOWLEDGED"}:
                raise FaqTransitionError("alert is already resolved")
            now = datetime.now(UTC)
            updates = {
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
            audit = self._audit("ALERT", alert_id, f"ALERT_{action}D", actor, current.owner_unit_id, reason)
            return BudgetState(
                revision=state.revision + 1,
                policies=state.policies,
                alerts=alerts,
                deliveries=state.deliveries,
                audits=(*state.audits, audit),
            ), {"alert": updated.model_dump(mode="json")}

        return self._repository.mutate(operation)

