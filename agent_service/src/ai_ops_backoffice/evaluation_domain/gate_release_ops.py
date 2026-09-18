"""Release verification and activation helpers for quality gates."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from operations_core.access import ActorContext

from .errors import EvaluationDomainError, EvaluationValidationError
from .gate_models import (
    ActivationAuditRecord,
    ActiveReleasePointer,
    BreakGlassRequest,
    GateDecision,
    GateMode,
    GatePolicyVersion,
    TargetType,
)
from .gate_repository import QualityGateRepository
from .runner_models import TargetManifest

__all__ = [
    "GateBlockedError",
    "activate_target",
    "create_break_glass",
    "resolve_active_policy_version",
    "verify_release_gate",
]


class GateBlockedError(EvaluationDomainError):
    """Raised when release promotion is blocked by an active quality gate."""


def resolve_active_policy_version(
    gate_repo: QualityGateRepository,
    *,
    policy_id: str,
    policy_version: int | None = None,
) -> tuple[GatePolicyVersion | None, int | None]:
    policy = gate_repo.get_policy(policy_id)
    active_ver_num = policy_version or (policy.active_version if policy else None)
    if not policy or not active_ver_num:
        return None, active_ver_num
    return gate_repo.get_version(policy_id, active_ver_num), active_ver_num


def filter_valid_decisions(
    decisions: list[GateDecision],
    *,
    now: datetime,
    target_manifest_hash: str,
    tenant_id: str | None = None,
    active_policy_ver: GatePolicyVersion | None = None,
) -> list[GateDecision]:
    valid = [
        decision
        for decision in decisions
        if decision.is_valid
        and decision.valid_until > now
        and decision.target_manifest_hash == target_manifest_hash
        and (tenant_id is None or decision.tenant_id == tenant_id)
    ]
    if active_policy_ver is not None:
        valid = [
            decision
            for decision in valid
            if decision.policy_id == active_policy_ver.policy_id
            and decision.policy_version == active_policy_ver.version
        ]
    return [
        decision
        for decision in valid
        if getattr(decision, "is_eval_eligible", True) is True
    ]


def _unexpired_exceptions(decision: GateDecision, *, now: datetime) -> list[Any]:
    return [
        exception
        for exception in decision.exceptions
        if exception.is_active and exception.expires_at > now
    ]


def _blocked_or_warning(
    *,
    mode: GateMode,
    enforce_message: str,
    warning: str,
    policy_id: str,
    policy_version: int | None,
    tenant_id: str | None,
    decision_id: str | None = None,
) -> dict[str, Any]:
    if mode == "ENFORCE":
        raise GateBlockedError(enforce_message)
    result: dict[str, Any] = {
        "status": "ALLOWED_WITH_WARNING",
        "warning": warning,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "tenant_id": tenant_id,
    }
    if decision_id is not None:
        result["decision_id"] = decision_id
    return result


def _passed_result(
    *,
    decision: GateDecision,
    policy_id: str,
) -> dict[str, Any]:
    return {
        "status": "PASSED",
        "decision_id": decision.decision_id,
        "policy_id": policy_id,
        "policy_version": decision.policy_version,
        "tenant_id": decision.tenant_id,
    }


def verify_release_gate(
    gate_repo: QualityGateRepository,
    *,
    target_manifest_hash: str,
    policy_id: str = "default-gate-policy",
    tenant_id: str | None = None,
    environment: str = "prod",
    policy_version: int | None = None,
    target_type: str | None = None,
) -> dict[str, Any]:
    """Validates release target manifest against active policy, tenant, and version."""

    _ = environment, target_type
    active_version, active_ver_num = resolve_active_policy_version(
        gate_repo,
        policy_id=policy_id,
        policy_version=policy_version,
    )
    decisions = gate_repo.list_decisions(target_manifest_hash, tenant_id=tenant_id)
    now = datetime.now(timezone.utc)
    valid_decisions = filter_valid_decisions(
        decisions,
        now=now,
        target_manifest_hash=target_manifest_hash,
        tenant_id=tenant_id,
        active_policy_ver=active_version,
    )
    mode: GateMode = active_version.mode if active_version else "REPORT_ONLY"

    if not valid_decisions:
        return _blocked_or_warning(
            mode=mode,
            enforce_message=(
                "Release blocked: No valid quality gate decision exists for manifest "
                f"'{target_manifest_hash}' under policy '{policy_id}'"
                + (f" v{active_ver_num}" if active_ver_num else "")
                + (f" tenant '{tenant_id}'" if tenant_id else "")
            ),
            warning="No quality gate decision found for manifest",
            policy_id=policy_id,
            policy_version=active_ver_num,
            tenant_id=tenant_id,
        )

    latest_dec = max(valid_decisions, key=lambda decision: decision.created_at)
    if latest_dec.decision in {"PASS", "EXCEPTION_APPROVED"}:
        if (
            latest_dec.decision == "EXCEPTION_APPROVED"
            and not _unexpired_exceptions(latest_dec, now=now)
            and mode == "ENFORCE"
        ):
            raise GateBlockedError(
                f"Release blocked: Gate exception for decision "
                f"'{latest_dec.decision_id}' has expired"
            )
        return _passed_result(decision=latest_dec, policy_id=policy_id)

    return _blocked_or_warning(
        mode=mode,
        enforce_message=(
            f"Release blocked by gate policy '{policy_id}': "
            f"{'; '.join(latest_dec.blocking_reasons)}"
        ),
        warning=f"Quality gate reported failures: {'; '.join(latest_dec.blocking_reasons)}",
        policy_id=policy_id,
        policy_version=latest_dec.policy_version,
        tenant_id=latest_dec.tenant_id,
        decision_id=latest_dec.decision_id,
    )


def create_break_glass(
    gate_repo: QualityGateRepository,
    *,
    tenant_id: str,
    environment: str = "prod",
    target_type: TargetType,
    candidate_manifest_hash: str,
    reason: str,
    authorized_by: str,
    requested_by: str,
    validity_hours: int = 12,
) -> BreakGlassRequest:
    """Creates an emergency break-glass authorization with strict expiration and scope."""
    now = datetime.now(timezone.utc)
    bg = BreakGlassRequest(
        break_glass_id=f"bg_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        environment=environment,
        target_type=target_type,
        candidate_manifest_hash=candidate_manifest_hash,
        reason=reason.strip(),
        authorized_by=authorized_by.strip(),
        requested_by=requested_by.strip(),
        expires_at=now + timedelta(hours=validity_hours),
        created_at=now,
        is_used=False,
    )
    gate_repo.save_break_glass(bg)
    return bg


def _consume_break_glass(
    gate_repo: QualityGateRepository,
    *,
    break_glass_id: str,
    tenant_id: str,
    environment: str,
    target_type: TargetType,
    candidate_manifest_hash: str,
    now: datetime,
) -> str:
    bg = gate_repo.get_break_glass(break_glass_id)
    if not bg:
        raise EvaluationValidationError(f"Break-glass request '{break_glass_id}' not found")
    if bg.is_used:
        raise EvaluationValidationError(
            f"Break-glass request '{break_glass_id}' has already been used"
        )
    if bg.expires_at < now:
        raise EvaluationValidationError(f"Break-glass request '{break_glass_id}' has expired")
    if bg.tenant_id != tenant_id or bg.environment != environment or bg.target_type != target_type:
        raise EvaluationValidationError(
            "Break-glass scope mismatch (tenant, environment, or target_type)"
        )
    if bg.candidate_manifest_hash != candidate_manifest_hash:
        raise EvaluationValidationError(
            f"Break-glass manifest hash mismatch: authorized for "
            f"'{bg.candidate_manifest_hash}', attempted '{candidate_manifest_hash}'"
        )
    gate_repo.save_break_glass(bg.model_copy(update={"is_used": True}))
    return break_glass_id


def _decision_id_for_activation(
    gate_repo: QualityGateRepository,
    *,
    tenant_id: str,
    candidate_manifest_hash: str,
    policy_id: str,
    now: datetime,
) -> str:
    active_policy_ver, active_ver_num = resolve_active_policy_version(
        gate_repo, policy_id=policy_id
    )
    mode: GateMode = active_policy_ver.mode if active_policy_ver else "REPORT_ONLY"
    decisions = gate_repo.list_decisions(
        target_manifest_hash=candidate_manifest_hash,
        tenant_id=tenant_id,
    )
    valid_decisions = filter_valid_decisions(
        decisions,
        now=now,
        target_manifest_hash=candidate_manifest_hash,
        tenant_id=tenant_id,
        active_policy_ver=active_policy_ver,
    )
    if not valid_decisions:
        if mode == "ENFORCE":
            raise GateBlockedError(
                f"Activation blocked by gate: No valid eligible decision exists for manifest "
                f"'{candidate_manifest_hash}' under policy '{policy_id}'"
                + (f" v{active_ver_num}" if active_ver_num else "")
            )
        return "unverified_report_only"

    latest_dec = max(valid_decisions, key=lambda decision: decision.created_at)
    if latest_dec.decision == "EXCEPTION_APPROVED":
        if not _unexpired_exceptions(latest_dec, now=now) and mode == "ENFORCE":
            raise GateBlockedError(
                f"Activation blocked: Gate exception for decision "
                f"'{latest_dec.decision_id}' has expired"
            )
    elif latest_dec.decision != "PASS" and mode == "ENFORCE":
        raise GateBlockedError(
            f"Activation blocked by gate policy '{policy_id}': "
            f"{'; '.join(latest_dec.blocking_reasons)}"
        )
    return latest_dec.decision_id


def activate_target(
    gate_repo: QualityGateRepository,
    *,
    tenant_id: str,
    environment: str = "prod",
    target_type: TargetType,
    candidate_manifest: TargetManifest,
    active_version_ref: str,
    actor: ActorContext,
    policy_id: str = "default-gate-policy",
    expected_pointer_etag: int | None = None,
    break_glass_id: str | None = None,
) -> ActiveReleasePointer:
    """Enforces quality gate rules before updating active pointer in atomic CAS."""
    now = datetime.now(timezone.utc)
    pointer_id = f"{tenant_id}:{environment}:{target_type}"
    current_pointer = gate_repo.get_active_pointer(tenant_id, environment, target_type)

    is_break_glass = False
    resolved_break_glass_id = None
    if break_glass_id:
        resolved_break_glass_id = _consume_break_glass(
            gate_repo,
            break_glass_id=break_glass_id,
            tenant_id=tenant_id,
            environment=environment,
            target_type=target_type,
            candidate_manifest_hash=candidate_manifest.manifest_hash,
            now=now,
        )
        is_break_glass = True
        decision_id = "break_glass"
    else:
        decision_id = _decision_id_for_activation(
            gate_repo,
            tenant_id=tenant_id,
            candidate_manifest_hash=candidate_manifest.manifest_hash,
            policy_id=policy_id,
            now=now,
        )

    new_etag = (current_pointer.etag + 1) if current_pointer else 1
    new_pointer = ActiveReleasePointer(
        pointer_id=pointer_id,
        tenant_id=tenant_id,
        environment=environment,
        target_type=target_type,
        active_manifest_hash=candidate_manifest.manifest_hash,
        active_version_ref=active_version_ref,
        active_target_manifest=candidate_manifest.model_dump(mode="json")
        if hasattr(candidate_manifest, "model_dump")
        else dict(candidate_manifest),
        decision_id=decision_id,
        etag=new_etag,
        updated_at=now,
        updated_by=actor.user_id,
        previous_manifest_hash=current_pointer.active_manifest_hash if current_pointer else None,
        is_break_glass=is_break_glass,
        break_glass_id=resolved_break_glass_id,
    )
    gate_repo.save_active_pointer(new_pointer, expected_etag=expected_pointer_etag)

    audit = ActivationAuditRecord(
        activation_id=f"act_{uuid.uuid4().hex[:12]}",
        pointer_id=pointer_id,
        tenant_id=tenant_id,
        environment=environment,
        target_type=target_type,
        from_manifest_hash=current_pointer.active_manifest_hash if current_pointer else None,
        to_manifest_hash=candidate_manifest.manifest_hash,
        decision_id=decision_id if not is_break_glass else None,
        is_break_glass=is_break_glass,
        break_glass_id=resolved_break_glass_id,
        activated_by=actor.user_id,
        activated_at=now,
    )
    gate_repo.save_activation_audit(audit)
    return new_pointer
