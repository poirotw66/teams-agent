"""Budget policy allocation and lifecycle use-case helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from operations_core.access import ActorContext

from ..faq_domain.errors import (
    FaqNotFoundError,
    FaqValidationError,
    FaqVersionConflictError,
)
from .models import BudgetPolicy, BudgetState
from .ops_common import authorize, build_audit
from .repository import BudgetRepository

__all__ = [
    "create_policy",
    "ensure_personal_policy",
    "list_policies",
    "policy_detail",
    "set_policy_enabled",
    "update_policy",
]


def list_policies(repository: BudgetRepository, *, actor: ActorContext) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json")
        for item in repository.load().policies
        if actor.has_capability("ops.budget.read") and actor.allows_owner_unit(item.owner_unit_id)
    ]


def policy_detail(
    repository: BudgetRepository,
    policy_id: str,
    *,
    actor: ActorContext,
) -> dict[str, Any]:
    policy = next(
        (item for item in repository.load().policies if item.policy_id == policy_id),
        None,
    )
    if policy is None:
        raise FaqNotFoundError(policy_id)
    authorize(actor, "ops.budget.read", policy.owner_unit_id)
    return policy.model_dump(mode="json")


def create_policy(
    repository: BudgetRepository,
    notification_targets: dict[str, str],
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
    authorize(actor, "ops.budget.write", owner_unit_id)
    if warning_threshold >= critical_threshold:
        raise FaqValidationError("warning threshold must be lower than critical threshold")
    unknown = set(notification_target_ids) - notification_targets.keys()
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
        audit = build_audit(
            "BUDGET_POLICY", policy.policy_id, "BUDGET_POLICY_CREATED", actor, owner_unit_id
        )
        return BudgetState(
            revision=state.revision + 1,
            policies=(*state.policies, policy),
            alerts=state.alerts,
            deliveries=state.deliveries,
            audits=(*state.audits, audit),
        ), {"policy": policy.model_dump(mode="json")}

    return repository.mutate(operation)


def set_policy_enabled(
    repository: BudgetRepository,
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
        authorize(actor, "ops.budget.write", current.owner_unit_id)
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
        audit = build_audit("BUDGET_POLICY", policy_id, action, actor, current.owner_unit_id, reason)
        return BudgetState(
            revision=state.revision + 1,
            policies=policies,
            alerts=state.alerts,
            deliveries=state.deliveries,
            audits=(*state.audits, audit),
        ), {"policy": updated.model_dump(mode="json")}

    return repository.mutate(operation)


def update_policy(
    repository: BudgetRepository,
    notification_targets: dict[str, str],
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
    if set(notification_target_ids) - notification_targets.keys():
        raise FaqValidationError("notification targets must be preconfigured")

    def operation(state: BudgetState) -> tuple[BudgetState, dict[str, Any]]:
        current = next((item for item in state.policies if item.policy_id == policy_id), None)
        if current is None:
            raise FaqNotFoundError(policy_id)
        authorize(actor, "ops.budget.write", current.owner_unit_id)
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
        audit = build_audit(
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

    return repository.mutate(operation)


def ensure_personal_policy(
    repository: BudgetRepository,
    notification_targets: dict[str, str],
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
    state = repository.load()
    existing = next(
        (
            policy
            for policy in state.policies
            if (
                policy.scope_type == "PERSONAL"
                and policy.scope_id == user_id
                and policy.period == "DAILY"
                and policy.measure == "TWD"
            )
        ),
        None,
    )
    if existing:
        return existing.model_dump(mode="json")

    target_ids = notification_target_ids or tuple(notification_targets.keys())
    created = create_policy(
        repository,
        notification_targets,
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
