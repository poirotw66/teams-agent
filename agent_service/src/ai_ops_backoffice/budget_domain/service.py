"""Budget domain service facade; use-case logic lives in sibling ops modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from operations_core.access import ActorContext

from . import alert_ops, delivery_ops, policy_ops
from .repository import BudgetRepository

__all__ = ["BudgetService"]


class BudgetService:
    def __init__(
        self,
        repository: BudgetRepository,
        *,
        notification_targets: dict[str, str],
    ) -> None:
        self._repository = repository
        self._notification_targets = notification_targets

    def list_policies(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        return policy_ops.list_policies(self._repository, actor=actor)

    def policy_detail(self, policy_id: str, *, actor: ActorContext) -> dict[str, Any]:
        return policy_ops.policy_detail(self._repository, policy_id, actor=actor)

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
        return policy_ops.create_policy(
            self._repository,
            self._notification_targets,
            scope_type=scope_type,
            scope_id=scope_id,
            period=period,
            measure=measure,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            owner_unit_id=owner_unit_id,
            notification_target_ids=notification_target_ids,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            actor=actor,
        )

    def set_policy_enabled(
        self,
        policy_id: str,
        *,
        enabled: bool,
        expected_etag: int,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return policy_ops.set_policy_enabled(
            self._repository,
            policy_id,
            enabled=enabled,
            expected_etag=expected_etag,
            reason=reason,
            actor=actor,
        )

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
        return policy_ops.update_policy(
            self._repository,
            self._notification_targets,
            policy_id,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            notification_target_ids=notification_target_ids,
            expected_etag=expected_etag,
            actor=actor,
        )

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
        return alert_ops.evaluate(
            self._repository,
            self._notification_targets,
            policy_id,
            period_key=period_key,
            actual_value=actual_value,
            coverage=coverage,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            actor=actor,
        )

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
        return alert_ops.trigger_operational_alert(
            self._repository,
            self._notification_targets,
            alert_type=alert_type,
            severity=severity,
            scope_type=scope_type,
            scope_id=scope_id,
            period_key=period_key,
            owner_unit_id=owner_unit_id,
            summary=summary,
            actor=actor,
            notification_target_ids=notification_target_ids,
            threshold=threshold,
            actual_value=actual_value,
            coverage=coverage,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
        )

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
        return policy_ops.ensure_personal_policy(
            self._repository,
            self._notification_targets,
            user_id,
            owner_unit_id=owner_unit_id,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            notification_target_ids=notification_target_ids,
            pricing_version=pricing_version,
            exchange_rate_version=exchange_rate_version,
            actor=actor,
        )

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
        return alert_ops.list_alerts(
            self._repository,
            actor=actor,
            alert_type=alert_type,
            severity=severity,
            status=status,
            scope_type=scope_type,
            scope_id=scope_id,
        )

    def alert_detail(self, alert_id: str, *, actor: ActorContext) -> dict[str, Any]:
        return alert_ops.alert_detail(self._repository, alert_id, actor=actor)

    def record_delivery_attempt(
        self,
        delivery_id: str,
        *,
        success: bool,
        error: str | None,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return delivery_ops.record_delivery_attempt(
            self._repository,
            delivery_id,
            success=success,
            error=error,
            actor=actor,
        )

    def retry_delivery(
        self,
        delivery_id: str,
        *,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return delivery_ops.retry_delivery(self._repository, delivery_id, actor=actor)

    def change_alert(
        self,
        alert_id: str,
        *,
        action: Literal["ACKNOWLEDGE", "RESOLVE"],
        expected_etag: int,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return alert_ops.change_alert(
            self._repository,
            alert_id,
            action=action,
            expected_etag=expected_etag,
            reason=reason,
            actor=actor,
        )

    def purge_expired(
        self,
        *,
        retention_days: int = 365,
        actor: ActorContext | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return delivery_ops.purge_expired(
            self._repository,
            retention_days=retention_days,
            actor=actor,
            now=now,
        )
