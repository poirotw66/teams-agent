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

from .faq_domain.errors import (
    FaqAuthorizationError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BudgetPolicy(StrictModel):
    policy_id: str
    scope_type: Literal["PERSONAL", "SERVICE", "TEAM", "TENANT", "GLOBAL"]
    scope_id: str
    period: Literal["DAILY", "MONTHLY"]
    measure: Literal["TWD", "USD", "TOKEN", "LLM_CALL_COUNT"]
    warning_threshold: float = Field(gt=0)
    critical_threshold: float = Field(gt=0)
    enabled: bool = True
    effective_at: datetime
    expires_at: datetime | None = None
    owner_unit_id: str
    notification_target_ids: tuple[str, ...]
    pricing_version: str
    exchange_rate_version: str
    etag: int = Field(default=1, ge=1)
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class AlertEvent(StrictModel):
    alert_id: str
    policy_id: str
    alert_type: Literal["BUDGET_THRESHOLD"] = "BUDGET_THRESHOLD"
    severity: Literal["WARNING", "CRITICAL"]
    scope_type: str
    scope_id: str
    period_key: str
    suppression_key: str
    threshold: float
    actual_value: float
    coverage: float = Field(ge=0, le=1)
    pricing_version: str
    exchange_rate_version: str
    status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"] = "OPEN"
    owner_unit_id: str
    first_triggered_at: datetime
    last_triggered_at: datetime
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    etag: int = Field(default=1, ge=1)


class NotificationDelivery(StrictModel):
    delivery_id: str
    alert_id: str
    target_id: str
    channel: Literal["TEAMS", "EMAIL", "NOTIFICATION_CENTER"]
    status: Literal["PENDING", "SENT", "FAILED"] = "PENDING"
    summary: str
    attempt_count: int = 0
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class BudgetAuditEvent(StrictModel):
    audit_id: str
    target_type: Literal["BUDGET_POLICY", "ALERT"]
    target_id: str
    action: str
    actor_id: str
    actor_role: str
    owner_unit_id: str
    reason: str | None = None
    occurred_at: datetime


class BudgetState(StrictModel):
    revision: int = 0
    policies: tuple[BudgetPolicy, ...] = ()
    alerts: tuple[AlertEvent, ...] = ()
    deliveries: tuple[NotificationDelivery, ...] = ()
    audits: tuple[BudgetAuditEvent, ...] = ()


Mutation = Callable[[BudgetState], tuple[BudgetState, dict[str, Any]]]


class BudgetRepository(Protocol):
    def load(self) -> BudgetState:
        ...

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        ...


class InMemoryBudgetRepository:
    def __init__(self) -> None:
        self._state = BudgetState()
        self._lock = threading.RLock()

    def load(self) -> BudgetState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        with self._lock:
            next_state, result = operation(self._state.model_copy(deep=True))
            if next_state.revision != self._state.revision + 1:
                raise FaqVersionConflictError("budget state revision must increment")
            self._state = next_state
            return result


class FileBudgetRepository(InMemoryBudgetRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")

    def _read(self) -> BudgetState:
        if not self._path.exists():
            return BudgetState()
        return BudgetState.model_validate_json(self._path.read_text(encoding="utf-8"))

    def load(self) -> BudgetState:
        with self._lock:
            return self._read()

    def _write(self, state: BudgetState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(state.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            directory = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        import fcntl

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                current = self._read()
                next_state, result = operation(current)
                if next_state.revision != current.revision + 1:
                    raise FaqVersionConflictError("budget state revision must increment")
                self._write(next_state)
                return result
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


class FirestoreBudgetRepository:
    def __init__(
        self,
        client: Any,
        *,
        collection: str = "ai_ops_budget_state",
        transaction_runner: Any | None = None,
    ) -> None:
        self._client = client
        self._state = client.collection(collection).document("current")
        self._transaction_runner = transaction_runner

    def load(self) -> BudgetState:
        snapshot = self._state.get()
        return BudgetState.model_validate(snapshot.to_dict()) if snapshot.exists else BudgetState()

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        def transaction_operation(transaction: Any) -> dict[str, Any]:
            snapshot = self._state.get(transaction=transaction)
            current = BudgetState.model_validate(snapshot.to_dict()) if snapshot.exists else BudgetState()
            next_state, result = operation(current)
            if next_state.revision != current.revision + 1:
                raise FaqVersionConflictError("budget state revision must increment")
            transaction.set(self._state, next_state.model_dump(mode="python"))
            return result

        if self._transaction_runner is not None:
            return self._transaction_runner(transaction_operation, self._client.transaction())
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("FIRESTORE budget repository requires google-cloud-firestore") from error
        return transactional(transaction_operation)(self._client.transaction())


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

    def list_alerts(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        state = self._repository.load()
        return [
            {
                **item.model_dump(mode="json"),
                "deliveries": [
                    delivery.model_dump(mode="json")
                    for delivery in state.deliveries
                    if delivery.alert_id == item.alert_id
                ],
            }
            for item in reversed(state.alerts)
            if actor.has_capability("ops.alerts.read") and actor.allows_owner_unit(item.owner_unit_id)
        ]

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
