"""Quality gate service: policies, decisions, release activation, and schedules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from operations_core.access import ActorContext

from . import gate_case_ops, gate_policy_ops, gate_release_ops
from .errors import EvaluationNotFoundError, EvaluationValidationError
from .gate_evaluator import GateEvaluator
from .gate_models import (
    ActiveReleasePointer,
    BreakGlassRequest,
    EvalSchedule,
    GateDecision,
    GateException,
    GateMode,
    GatePolicy,
    GatePolicyVersion,
    QualityCaseLink,
    SourceImpactResult,
    TargetType,
)
from .gate_release_ops import GateBlockedError
from .gate_repository import QualityGateRepository
from .repository import EvaluationRepository
from .runner_models import TargetManifest

__all__ = ["GateBlockedError", "QualityGateService"]


class QualityGateService:
    """Service managing gate policies, decisions, exceptions, source impact analysis, and schedules."""

    def __init__(
        self,
        eval_repository: EvaluationRepository,
        gate_repository: QualityGateRepository | None = None,
        evaluator: GateEvaluator | None = None,
    ) -> None:
        self._eval_repo = eval_repository
        self._gate_repo = gate_repository or QualityGateRepository()
        self._evaluator = evaluator or GateEvaluator()
        gate_policy_ops.seed_default_policy(self._gate_repo)

    @property
    def repository(self) -> QualityGateRepository:
        return self._gate_repo

    def create_policy(
        self,
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
        return gate_policy_ops.create_policy(
            self._gate_repo,
            policy_id=policy_id,
            tenant_id=tenant_id,
            name=name,
            created_by=created_by,
            description=description,
            mode=mode,
            minimum_coverage=minimum_coverage,
            minimum_pass_rate=minimum_pass_rate,
            max_regression_count=max_regression_count,
            required_set_version_ids=required_set_version_ids,
        )

    def create_policy_version(
        self,
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
        return gate_policy_ops.create_policy_version(
            self._gate_repo,
            policy_id=policy_id,
            name=name,
            created_by=created_by,
            description=description,
            mode=mode,
            minimum_coverage=minimum_coverage,
            minimum_pass_rate=minimum_pass_rate,
            max_regression_count=max_regression_count,
            required_set_version_ids=required_set_version_ids,
        )

    def approve_policy_version(
        self,
        *,
        policy_id: str,
        version: int,
        approved_by: str,
    ) -> GatePolicyVersion:
        return gate_policy_ops.approve_policy_version(
            self._gate_repo,
            policy_id=policy_id,
            version=version,
            approved_by=approved_by,
        )

    def activate_policy_version(
        self,
        *,
        policy_id: str,
        version: int,
        mode: GateMode | None = None,
        actor: ActorContext,
    ) -> GatePolicyVersion:
        return gate_policy_ops.activate_policy_version(
            self._gate_repo,
            policy_id=policy_id,
            version=version,
            mode=mode,
            actor=actor,
        )

    def evaluate_decision(
        self,
        *,
        policy_id: str,
        policy_version: int | None = None,
        run_id: str,
        target_manifest_hash: str,
        actor: ActorContext,
    ) -> GateDecision:
        policy = self._gate_repo.get_policy(policy_id)
        if not policy:
            raise EvaluationNotFoundError(f"Gate policy '{policy_id}' not found")

        v_num = policy_version or policy.active_version or policy.current_version
        version = self._gate_repo.get_version(policy_id, v_num)
        if not version:
            raise EvaluationNotFoundError(f"Policy version '{policy_id}:v{v_num}' not found")

        state = self._eval_repo.load()
        run = next((item for item in state.runs if item.run_id == run_id), None)
        if not run:
            raise EvaluationNotFoundError(f"Evaluation run '{run_id}' not found")

        decision = self._evaluator.evaluate(
            policy_version=version,
            run=run,
            target_manifest_hash=target_manifest_hash,
        )
        self._gate_repo.save_decision(decision)
        return decision

    def request_exception(
        self,
        *,
        decision_id: str,
        reason: str,
        requested_by: str,
        validity_hours: int = 24,
    ) -> GateException:
        decision = self._gate_repo.get_decision(decision_id)
        if not decision:
            raise EvaluationNotFoundError(f"Gate decision '{decision_id}' not found")

        is_safety_critical = any(
            "critical failure" in reason_text.lower()
            or "safety" in reason_text.lower()
            or "acl" in reason_text.lower()
            for reason_text in decision.blocking_reasons
        )
        if is_safety_critical:
            raise EvaluationValidationError(
                "Critical safety violations (ACL leak, prompt injection, unauthorized side-effects) "
                "cannot be granted gate exceptions"
            )

        now = datetime.now(timezone.utc)
        exception = GateException(
            exception_id=f"gexc_{decision_id[:8]}_{int(now.timestamp())}",
            decision_id=decision_id,
            reason=reason,
            requested_by=requested_by,
            requested_at=now,
            expires_at=now + timedelta(hours=validity_hours),
            is_active=False,
            disallowed_critical_failure=False,
        )
        self._gate_repo.save_exception(exception)
        return exception

    def approve_exception(
        self,
        *,
        exception_id: str,
        approver_id: str,
    ) -> GateException:
        exception = self._gate_repo.get_exception(exception_id)
        if not exception:
            raise EvaluationNotFoundError(f"Gate exception '{exception_id}' not found")

        if exception.requested_by == approver_id:
            raise EvaluationValidationError(
                f"Requester '{exception.requested_by}' cannot approve their own exception"
            )

        now = datetime.now(timezone.utc)
        if exception.expires_at < now:
            raise EvaluationValidationError("Exception request has already expired")

        if exception.approved_by_1 is None:
            updated = exception.model_copy(
                update={"approved_by_1": approver_id, "approved_at_1": now}
            )
            self._gate_repo.save_exception(updated)
            return updated
        if exception.approved_by_2 is None:
            if exception.approved_by_1 == approver_id:
                raise EvaluationValidationError(
                    "Second approver must be distinct from the first approver"
                )
            updated = exception.model_copy(
                update={
                    "approved_by_2": approver_id,
                    "approved_at_2": now,
                    "is_active": True,
                }
            )
            self._gate_repo.save_exception(updated)

            decision = self._gate_repo.get_decision(exception.decision_id)
            if decision:
                new_dec = decision.model_copy(
                    update={
                        "decision": "EXCEPTION_APPROVED",
                        "exceptions": decision.exceptions + (updated,),
                    }
                )
                self._gate_repo.save_decision(new_dec)
            return updated
        return exception

    def verify_release_gate(
        self,
        *,
        target_manifest_hash: str,
        policy_id: str = "default-gate-policy",
        tenant_id: str | None = None,
        environment: str = "prod",
        policy_version: int | None = None,
        target_type: str | None = None,
    ) -> dict[str, Any]:
        """Validates release target manifest against active policy, tenant, and version.

        Matching ``activate_target`` rules: hash alone is insufficient; decisions must
        bind the active policy version and tenant (Spec 7.1).
        """
        return gate_release_ops.verify_release_gate(
            self._gate_repo,
            target_manifest_hash=target_manifest_hash,
            policy_id=policy_id,
            tenant_id=tenant_id,
            environment=environment,
            policy_version=policy_version,
            target_type=target_type,
        )

    def get_active_pointer(
        self, tenant_id: str, environment: str, target_type: TargetType
    ) -> ActiveReleasePointer | None:
        return self._gate_repo.get_active_pointer(tenant_id, environment, target_type)

    def list_active_pointers(
        self, tenant_id: str | None = None
    ) -> list[ActiveReleasePointer]:
        return self._gate_repo.list_active_pointers(tenant_id)

    def create_break_glass(
        self,
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
        """Creates an emergency break-glass authorization with strict expiration and scope (Spec 7.1)."""
        return gate_release_ops.create_break_glass(
            self._gate_repo,
            tenant_id=tenant_id,
            environment=environment,
            target_type=target_type,
            candidate_manifest_hash=candidate_manifest_hash,
            reason=reason,
            authorized_by=authorized_by,
            requested_by=requested_by,
            validity_hours=validity_hours,
        )

    def activate_target(
        self,
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
        """Enforces quality gate rules before updating active pointer in atomic CAS (Spec 7.1, F05)."""
        return gate_release_ops.activate_target(
            self._gate_repo,
            tenant_id=tenant_id,
            environment=environment,
            target_type=target_type,
            candidate_manifest=candidate_manifest,
            active_version_ref=active_version_ref,
            actor=actor,
            policy_id=policy_id,
            expected_pointer_etag=expected_pointer_etag,
            break_glass_id=break_glass_id,
        )

    def rollback_target(
        self,
        *,
        tenant_id: str,
        environment: str = "prod",
        target_type: TargetType,
        target_manifest: TargetManifest,
        active_version_ref: str,
        reason: str,
        actor: ActorContext,
        policy_id: str = "default-gate-policy",
        expected_pointer_etag: int | None = None,
        break_glass_id: str | None = None,
    ) -> ActiveReleasePointer:
        """Rolls back an active target to a previous version, requiring a valid decision or break-glass (Spec 7.1)."""
        _ = reason
        return self.activate_target(
            tenant_id=tenant_id,
            environment=environment,
            target_type=target_type,
            candidate_manifest=target_manifest,
            active_version_ref=active_version_ref,
            actor=actor,
            policy_id=policy_id,
            expected_pointer_etag=expected_pointer_etag,
            break_glass_id=break_glass_id,
        )

    def analyze_source_impact(
        self,
        *,
        source_type: str,
        source_id: str,
        source_version: str | None = None,
    ) -> SourceImpactResult:
        """Finds all eval cases and sets affected when an underlying document or FAQ is updated."""
        return gate_case_ops.analyze_source_impact(
            self._eval_repo,
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
        )

    def link_quality_case(
        self,
        *,
        run_id: str,
        execution_id: str,
        root_cause: str,
        actor: ActorContext,
    ) -> QualityCaseLink:
        """Links an evaluation execution failure to a deduplicated quality case."""
        return gate_case_ops.link_quality_case(
            self._gate_repo,
            run_id=run_id,
            execution_id=execution_id,
            root_cause=root_cause,
            actor=actor,
        )

    def resolve_quality_case(
        self,
        *,
        quality_case_id: str,
        resolution_run_id: str,
    ) -> QualityCaseLink:
        return gate_case_ops.resolve_quality_case(
            self._gate_repo,
            quality_case_id=quality_case_id,
            resolution_run_id=resolution_run_id,
        )

    def create_schedule(
        self,
        *,
        schedule_id: str,
        tenant_id: str,
        name: str,
        set_version_id: str,
        frequency: str = "DAILY",
        budget_limit_usd: float = 5.0,
        target_refs: dict[str, Any] | None = None,
        created_by: str,
    ) -> EvalSchedule:
        return gate_case_ops.create_schedule(
            self._gate_repo,
            schedule_id=schedule_id,
            tenant_id=tenant_id,
            name=name,
            set_version_id=set_version_id,
            frequency=frequency,
            budget_limit_usd=budget_limit_usd,
            target_refs=target_refs,
            created_by=created_by,
        )

    def update_schedule(
        self,
        *,
        schedule_id: str,
        is_enabled: bool | None = None,
        frequency: str | None = None,
        budget_limit_usd: float | None = None,
        target_refs: dict[str, Any] | None = None,
        updated_by: str,
    ) -> EvalSchedule:
        return gate_case_ops.update_schedule(
            self._gate_repo,
            schedule_id=schedule_id,
            is_enabled=is_enabled,
            frequency=frequency,
            budget_limit_usd=budget_limit_usd,
            target_refs=target_refs,
            updated_by=updated_by,
        )
