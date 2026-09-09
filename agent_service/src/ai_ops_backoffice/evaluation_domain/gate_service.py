from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agent_service.operations.access import ActorContext

from .errors import (
    EvaluationDomainError,
    EvaluationNotFoundError,
    EvaluationValidationError,
)
from .gate_evaluator import GateEvaluator
from .gate_models import (
    EvalSchedule,
    GateDecision,
    GateException,
    GateMode,
    GatePolicy,
    GatePolicyVersion,
    QualityCaseLink,
    SourceImpactResult,
)
from .gate_repository import QualityGateRepository
from .repository import EvaluationRepository


class GateBlockedError(EvaluationDomainError):
    """Raised when release promotion is blocked by an active quality gate."""


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
        self._seed_default_policy()

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
        existing = self._gate_repo.get_policy(policy_id)
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
        self._gate_repo.save_policy(policy)
        self._gate_repo.save_version(version)
        return policy, version

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
        policy = self._gate_repo.get_policy(policy_id)
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
        self._gate_repo.save_policy(updated_p)
        self._gate_repo.save_version(version)
        return version

    def approve_policy_version(
        self,
        *,
        policy_id: str,
        version: int,
        approved_by: str,
    ) -> GatePolicyVersion:
        v = self._gate_repo.get_version(policy_id, version)
        if not v:
            raise EvaluationNotFoundError(f"Policy version '{policy_id}:v{version}' not found")
        if v.created_by == approved_by:
            raise EvaluationValidationError(
                f"Author '{v.created_by}' cannot approve their own gate policy version"
            )
        now = datetime.now(timezone.utc)
        approved = v.model_copy(
            update={
                "status": "APPROVED",
                "approved_by": approved_by,
                "approved_at": now,
                "etag": v.etag + 1,
            }
        )
        self._gate_repo.save_version(approved)
        return approved

    def activate_policy_version(
        self,
        *,
        policy_id: str,
        version: int,
        mode: GateMode | None = None,
        actor: ActorContext,
    ) -> GatePolicyVersion:
        p = self._gate_repo.get_policy(policy_id)
        v = self._gate_repo.get_version(policy_id, version)
        if not p or not v:
            raise EvaluationNotFoundError(f"Policy version '{policy_id}:v{version}' not found")
        if v.status not in {"APPROVED", "ACTIVE"}:
            raise EvaluationValidationError(f"Cannot activate unapproved policy in status '{v.status}'")

        target_mode = mode or v.mode
        now = datetime.now(timezone.utc)
        active_ver = v.model_copy(
            update={
                "status": "ACTIVE",
                "mode": target_mode,
                "etag": v.etag + 1,
            }
        )
        self._gate_repo.save_version(active_ver)

        updated_p = p.model_copy(
            update={
                "active_version": version,
                "updated_by": actor.user_id,
                "updated_at": now,
            }
        )
        self._gate_repo.save_policy(updated_p)
        return active_ver

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
        v = self._gate_repo.get_version(policy_id, v_num)
        if not v:
            raise EvaluationNotFoundError(f"Policy version '{policy_id}:v{v_num}' not found")

        state = self._eval_repo.load()
        run = next((r for r in state.runs if r.run_id == run_id), None)
        if not run:
            raise EvaluationNotFoundError(f"Evaluation run '{run_id}' not found")

        decision = self._evaluator.evaluate(
            policy_version=v,
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

        # Security rule: safety critical failures cannot be exempted!
        is_safety_critical = any(
            "critical failure" in r.lower() or "safety" in r.lower() or "acl" in r.lower()
            for r in decision.blocking_reasons
        )
        if is_safety_critical:
            raise EvaluationValidationError(
                "Critical safety violations (ACL leak, prompt injection, unauthorized side-effects) "
                "cannot be granted gate exceptions"
            )

        now = datetime.now(timezone.utc)
        exc_id = f"gexc_{decision_id[:8]}_{int(now.timestamp())}"
        exc = GateException(
            exception_id=exc_id,
            decision_id=decision_id,
            reason=reason,
            requested_by=requested_by,
            requested_at=now,
            expires_at=now + timedelta(hours=validity_hours),
            is_active=False,
            disallowed_critical_failure=False,
        )
        self._gate_repo.save_exception(exc)
        return exc

    def approve_exception(
        self,
        *,
        exception_id: str,
        approver_id: str,
    ) -> GateException:
        exc = self._gate_repo.get_exception(exception_id)
        if not exc:
            raise EvaluationNotFoundError(f"Gate exception '{exception_id}' not found")

        if exc.requested_by == approver_id:
            raise EvaluationValidationError(
                f"Requester '{exc.requested_by}' cannot approve their own exception"
            )

        now = datetime.now(timezone.utc)
        if exc.expires_at < now:
            raise EvaluationValidationError("Exception request has already expired")

        # Dual approval requirement: needs two distinct reviewers
        if exc.approved_by_1 is None:
            updated = exc.model_copy(
                update={"approved_by_1": approver_id, "approved_at_1": now}
            )
            self._gate_repo.save_exception(updated)
            return updated
        elif exc.approved_by_2 is None:
            if exc.approved_by_1 == approver_id:
                raise EvaluationValidationError("Second approver must be distinct from the first approver")
            updated = exc.model_copy(
                update={
                    "approved_by_2": approver_id,
                    "approved_at_2": now,
                    "is_active": True,
                }
            )
            self._gate_repo.save_exception(updated)

            # Update decision to EXCEPTION_APPROVED
            decision = self._gate_repo.get_decision(exc.decision_id)
            if decision:
                new_dec = decision.model_copy(
                    update={
                        "decision": "EXCEPTION_APPROVED",
                        "exceptions": decision.exceptions + (updated,),
                    }
                )
                self._gate_repo.save_decision(new_dec)
            return updated
        return exc

    def verify_release_gate(
        self,
        *,
        target_manifest_hash: str,
        policy_id: str = "default-gate-policy",
    ) -> dict[str, Any]:
        """Validates that release target manifest satisfies active quality gate policy."""
        policy = self._gate_repo.get_policy(policy_id)
        active_ver_num = policy.active_version if policy else None
        active_version = (
            self._gate_repo.get_version(policy_id, active_ver_num)
            if (policy and active_ver_num)
            else None
        )

        decisions = self._gate_repo.list_decisions(target_manifest_hash)
        now = datetime.now(timezone.utc)
        valid_decisions = [
            d for d in decisions if d.is_valid and d.valid_until > now and d.target_manifest_hash == target_manifest_hash
        ]

        mode = active_version.mode if active_version else "REPORT_ONLY"

        if not valid_decisions:
            if mode == "ENFORCE":
                raise GateBlockedError(
                    f"Release blocked: No valid quality gate decision exists for manifest '{target_manifest_hash}'"
                )
            return {"status": "ALLOWED_WITH_WARNING", "warning": "No quality gate decision found for manifest"}

        latest_dec = max(valid_decisions, key=lambda d: d.created_at)
        if latest_dec.decision in {"PASS", "EXCEPTION_APPROVED"}:
            return {"status": "PASSED", "decision_id": latest_dec.decision_id}

        # Decision is FAIL
        if mode == "ENFORCE":
            raise GateBlockedError(
                f"Release blocked by gate policy '{policy_id}': {'; '.join(latest_dec.blocking_reasons)}"
            )
        return {
            "status": "ALLOWED_WITH_WARNING",
            "warning": f"Quality gate reported failures: {'; '.join(latest_dec.blocking_reasons)}",
            "decision_id": latest_dec.decision_id,
        }

    def analyze_source_impact(
        self,
        *,
        source_type: str,
        source_id: str,
        source_version: str | None = None,
    ) -> SourceImpactResult:
        """Finds all eval cases and sets affected when an underlying document or FAQ is updated."""
        state = self._eval_repo.load()
        affected_case_ids: set[str] = set()
        affected_rev_ids: set[str] = set()

        for rev in state.revisions:
            hit = False
            if rev.provenance and rev.provenance.source_id == source_id:
                hit = True
            for req in rev.evidence:
                for item in req.items:
                    if item.source_id == source_id:
                        hit = True
                        break
            if hit:
                affected_rev_ids.add(rev.revision_id)
                affected_case_ids.add(rev.case_id)

        affected_set_version_ids: set[str] = set()
        for sv in state.set_versions:
            if any(c_rev in affected_rev_ids for c_rev in sv.case_revision_ids):
                affected_set_version_ids.add(sv.set_version_id)

        return SourceImpactResult(
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
            affected_case_ids=tuple(sorted(affected_case_ids)),
            affected_revision_ids=tuple(sorted(affected_rev_ids)),
            affected_set_version_ids=tuple(sorted(affected_set_version_ids)),
            has_active_manifest_impact=len(affected_set_version_ids) > 0,
            requires_review_count=len(affected_rev_ids),
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
        existing = self._gate_repo.get_quality_case_by_execution(execution_id)
        if existing:
            return existing

        now = datetime.now(timezone.utc)
        qc_id = f"qc_{run_id[:8]}_{execution_id[:8]}"
        link = QualityCaseLink(
            quality_case_id=qc_id,
            eval_case_id=execution_id.split("_")[-1] if "_" in execution_id else execution_id,
            run_id=run_id,
            execution_id=execution_id,
            root_cause=root_cause,
            status="OPEN",
            created_at=now,
            updated_at=now,
        )
        self._gate_repo.save_quality_case(link)
        return link

    def resolve_quality_case(
        self,
        *,
        quality_case_id: str,
        resolution_run_id: str,
    ) -> QualityCaseLink:
        link = self._gate_repo.get_quality_case(quality_case_id)
        if not link:
            raise EvaluationNotFoundError(f"Quality case '{quality_case_id}' not found")

        now = datetime.now(timezone.utc)
        resolved = link.model_copy(
            update={
                "status": "RESOLVED",
                "resolution_run_id": resolution_run_id,
                "updated_at": now,
            }
        )
        self._gate_repo.save_quality_case(resolved)
        return resolved

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
        now = datetime.now(timezone.utc)
        schedule = EvalSchedule(
            schedule_id=schedule_id,
            tenant_id=tenant_id,
            name=name,
            set_version_id=set_version_id,
            frequency=frequency,  # type: ignore[arg-type]
            budget_limit_usd=budget_limit_usd,
            target_refs=target_refs or {},
            is_enabled=True,
            created_by=created_by,
            created_at=now,
            updated_by=created_by,
            updated_at=now,
        )
        self._gate_repo.save_schedule(schedule)
        return schedule

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
        schedule = self._gate_repo.get_schedule(schedule_id)
        if not schedule:
            raise EvaluationNotFoundError(f"Schedule '{schedule_id}' not found")
        now = datetime.now(timezone.utc)
        updates: dict[str, Any] = {"updated_by": updated_by, "updated_at": now}
        if is_enabled is not None:
            updates["is_enabled"] = is_enabled
        if frequency is not None:
            updates["frequency"] = frequency
        if budget_limit_usd is not None:
            updates["budget_limit_usd"] = budget_limit_usd
        if target_refs is not None:
            updates["target_refs"] = target_refs

        updated = schedule.model_copy(update=updates)
        self._gate_repo.save_schedule(updated)
        return updated

    def _seed_default_policy(self) -> None:
        """Seeds baseline gate policy."""
        now = datetime.now(timezone.utc)
        policy_id = "default-gate-policy"
        if not self._gate_repo.get_policy(policy_id):
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
            self._gate_repo.save_policy(policy)
            self._gate_repo.save_version(version)
