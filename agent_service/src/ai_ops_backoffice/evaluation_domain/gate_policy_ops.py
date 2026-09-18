"""Policy lifecycle helpers for quality gate governance."""

from __future__ import annotations

from datetime import datetime, timezone

from operations_core.access import ActorContext

from .errors import EvaluationNotFoundError, EvaluationValidationError
from .gate_models import GateMode, GatePolicy, GatePolicyVersion
from .gate_repository import QualityGateRepository

__all__ = [
    "activate_policy_version",
    "approve_policy_version",
    "create_policy",
    "create_policy_version",
    "seed_default_policy",
]


def create_policy(
    gate_repo: QualityGateRepository,
    *,
    policy_id: str,
    tenant_id: str,
    name: str,
    created_by: str,
    description: str = "",
    mode: GateMode = "REPORT_ONLY",
    minimum_coverage: float = 1.0,
    minimum_pass_rate: float = 0.95,
    max_regression_count: int = 0,
    required_set_version_ids: list[str] | None = None,
) -> tuple[GatePolicy, GatePolicyVersion]:
    existing = gate_repo.get_policy(policy_id)
    if existing:
        raise EvaluationValidationError(f"Gate policy '{policy_id}' already exists")

    now = datetime.now(timezone.utc)
    policy = GatePolicy(
        policy_id=policy_id,
        tenant_id=tenant_id,
        name=name,
        current_version=1,
        active_version=None,
        created_by=created_by,
        created_at=now,
        updated_by=created_by,
        updated_at=now,
    )
    version = GatePolicyVersion(
        policy_id=policy_id,
        version=1,
        name=name,
        description=description,
        mode=mode,
        minimum_coverage=minimum_coverage,
        minimum_pass_rate=minimum_pass_rate,
        max_regression_count=max_regression_count,
        required_set_version_ids=tuple(required_set_version_ids or []),
        status="DRAFT",
        created_by=created_by,
        created_at=now,
    )
    gate_repo.save_policy(policy)
    gate_repo.save_version(version)
    return policy, version


def create_policy_version(
    gate_repo: QualityGateRepository,
    *,
    policy_id: str,
    name: str,
    created_by: str,
    description: str = "",
    mode: GateMode = "REPORT_ONLY",
    minimum_coverage: float = 1.0,
    minimum_pass_rate: float = 0.95,
    max_regression_count: int = 0,
    required_set_version_ids: list[str] | None = None,
) -> GatePolicyVersion:
    policy = gate_repo.get_policy(policy_id)
    if not policy:
        raise EvaluationNotFoundError(f"Gate policy '{policy_id}' not found")

    now = datetime.now(timezone.utc)
    next_ver = policy.current_version + 1
    version = GatePolicyVersion(
        policy_id=policy_id,
        version=next_ver,
        name=name,
        description=description,
        mode=mode,
        minimum_coverage=minimum_coverage,
        minimum_pass_rate=minimum_pass_rate,
        max_regression_count=max_regression_count,
        required_set_version_ids=tuple(required_set_version_ids or []),
        status="DRAFT",
        created_by=created_by,
        created_at=now,
    )
    updated_p = policy.model_copy(
        update={
            "current_version": next_ver,
            "updated_by": created_by,
            "updated_at": now,
        }
    )
    gate_repo.save_policy(updated_p)
    gate_repo.save_version(version)
    return version


def approve_policy_version(
    gate_repo: QualityGateRepository,
    *,
    policy_id: str,
    version: int,
    approved_by: str,
) -> GatePolicyVersion:
    policy_version = gate_repo.get_version(policy_id, version)
    if not policy_version:
        raise EvaluationNotFoundError(f"Policy version '{policy_id}:v{version}' not found")
    if policy_version.created_by == approved_by:
        raise EvaluationValidationError(
            f"Author '{policy_version.created_by}' cannot approve their own gate policy version"
        )
    now = datetime.now(timezone.utc)
    approved = policy_version.model_copy(
        update={
            "status": "APPROVED",
            "approved_by": approved_by,
            "approved_at": now,
            "etag": policy_version.etag + 1,
        }
    )
    gate_repo.save_version(approved)
    return approved


def activate_policy_version(
    gate_repo: QualityGateRepository,
    *,
    policy_id: str,
    version: int,
    mode: GateMode | None = None,
    actor: ActorContext,
) -> GatePolicyVersion:
    policy = gate_repo.get_policy(policy_id)
    policy_version = gate_repo.get_version(policy_id, version)
    if not policy or not policy_version:
        raise EvaluationNotFoundError(f"Policy version '{policy_id}:v{version}' not found")
    if policy_version.status not in {"APPROVED", "ACTIVE"}:
        raise EvaluationValidationError(
            f"Cannot activate unapproved policy in status '{policy_version.status}'"
        )

    target_mode = mode or policy_version.mode
    now = datetime.now(timezone.utc)
    active_ver = policy_version.model_copy(
        update={
            "status": "ACTIVE",
            "mode": target_mode,
            "etag": policy_version.etag + 1,
        }
    )
    gate_repo.save_version(active_ver)

    updated_policy = policy.model_copy(
        update={
            "active_version": version,
            "updated_by": actor.user_id,
            "updated_at": now,
        }
    )
    gate_repo.save_policy(updated_policy)
    return active_ver


def seed_default_policy(gate_repo: QualityGateRepository) -> None:
    """Seeds baseline gate policy."""
    now = datetime.now(timezone.utc)
    policy_id = "default-gate-policy"
    if gate_repo.get_policy(policy_id):
        return
    policy = GatePolicy(
        policy_id=policy_id,
        tenant_id="default",
        name="預設品質發布門檻",
        current_version=1,
        active_version=1,
        created_by="system",
        created_at=now,
        updated_by="system",
        updated_at=now,
    )
    version = GatePolicyVersion(
        policy_id=policy_id,
        version=1,
        name="預設品質發布門檻",
        description="驗收覆蓋率100%，重大失敗零容忍",
        mode="REPORT_ONLY",
        minimum_coverage=1.0,
        minimum_pass_rate=0.95,
        max_regression_count=0,
        status="ACTIVE",
        created_by="system",
        created_at=now,
        approved_by="admin",
        approved_at=now,
    )
    gate_repo.save_policy(policy)
    gate_repo.save_version(version)
