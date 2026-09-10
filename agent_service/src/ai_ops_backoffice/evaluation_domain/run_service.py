from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from agent_service.operations.access import ActorContext

from .errors import (
    EvaluationAuthorizationError,
    EvaluationNotFoundError,
    EvaluationValidationError,
)
from .manifest import ManifestResolver
from .models import EvaluationAuditEvent
from .repository import EvaluationRepository
from .runner import EvaluationRunner
from .runner_models import (
    CaseExecution,
    EvaluationRun,
    MetricResult,
    MetricStatus,
    ReviewDecision,
    RunPreflightResult,
    TargetSide,
)
from .scorer import EvaluationScorer


class EvaluationRunService:
    """Manages lifecycle, preflight, dispatch, review, and rescoring of Evaluation Runs."""

    def __init__(
        self,
        repository: EvaluationRepository,
        manifest_resolver: ManifestResolver | None = None,
        runner: EvaluationRunner | None = None,
        scorer: EvaluationScorer | None = None,
    ) -> None:
        self._repo = repository
        self._resolver = manifest_resolver or ManifestResolver(repository)
        self._scorer = scorer or EvaluationScorer()
        self._runner = runner or EvaluationRunner(repository, scorer=self._scorer)

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str | None = None) -> None:
        if not actor.has_capability(capability):
            raise EvaluationAuthorizationError(f"Actor lacks capability: {capability}")
        if owner_unit_id and not actor.allows_owner_unit(owner_unit_id):
            raise EvaluationAuthorizationError(f"Actor lacks scope for owner unit: {owner_unit_id}")

    def preflight_run(
        self,
        set_version_id: str,
        baseline_target: dict[str, Any],
        candidate_target: dict[str, Any],
        limits: dict[str, Any] | None = None,
        actor: ActorContext | None = None,
    ) -> RunPreflightResult:
        if actor:
            self._authorize(actor, "ops.evals.read")
        return self._resolver.preflight_run(
            set_version_id=set_version_id,
            baseline_target=baseline_target,
            candidate_target=candidate_target,
            limits=limits,
        )

    def create_run(
        self,
        set_version_id: str,
        baseline_target: dict[str, Any],
        candidate_target: dict[str, Any],
        mode: str = "REAL_RAG",
        limits: dict[str, Any] | None = None,
        repetitions: int = 1,
        quality_case_id: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        actor: ActorContext | None = None,
        execute_inline: bool = True,
    ) -> dict[str, Any]:
        """Queues and executes an evaluation run."""
        if actor:
            self._authorize(actor, "ops.evals.run")

        limits = limits or {}
        # Preflight validation
        preflight = self._resolver.preflight_run(
            set_version_id=set_version_id,
            baseline_target=baseline_target,
            candidate_target=candidate_target,
            limits=limits,
        )
        if not preflight.is_valid:
            raise EvaluationValidationError(
                f"Run preflight rejected with errors: {'; '.join(preflight.blocking_errors)}"
            )

        set_version = self._repo.get_set_version(set_version_id)
        if not set_version:
            raise EvaluationNotFoundError(f"Set version {set_version_id} not found")

        eval_set = self._repo.get_set(set_version.set_id)
        owner_unit = eval_set.owner_unit_ids[0] if eval_set and eval_set.owner_unit_ids else "ALL"
        tenant_id = eval_set.tenant_id if eval_set else "default"

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        run = EvaluationRun(
            run_id=run_id,
            tenant_id=tenant_id,
            owner_unit_id=owner_unit,
            quality_case_id=quality_case_id,
            set_version_id=set_version_id,
            baseline_manifest=preflight.resolved_baseline_manifest,
            candidate_manifest=preflight.resolved_candidate_manifest,
            mode=mode if mode in {"REAL_RAG", "AGENT_SANDBOX"} else "OFFLINE_BENCHMARK",
            status="QUEUED",
            limits=limits,
            repetitions=repetitions,
            requested_by=actor.user_id if actor else "system",
            created_at=now,
            correlation_id=correlation_id,
        )

        state = self._repo.load()
        runs = list(state.runs)
        runs.append(run)
        new_state = state.model_copy(update={"runs": tuple(runs)})

        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="EVAL_RUN",
            entity_id=run_id,
            action="CREATE_RUN",
            actor_id=actor.user_id if actor else "system",
            actor_role=actor.role if actor else "SYSTEM",
            owner_unit_id=owner_unit,
            tenant_id=tenant_id,
            before=None,
            after={"run_id": run_id, "status": "QUEUED"},
            reason="Queued new evaluation run",
            occurred_at=now,
            correlation_id=correlation_id,
        )
        self._repo.commit_mutation(new_state, audit=audit)

        if execute_inline:
            run = self._runner.execute_run(run_id)

        return {"run": run.model_dump(mode="json")}

    def get_run(self, run_id: str, actor: ActorContext | None = None) -> dict[str, Any]:
        if actor:
            self._authorize(actor, "ops.evals.read")
        run = self._repo.get_run(run_id)
        if not run:
            raise EvaluationNotFoundError(f"Evaluation run {run_id} not found")
        return {"run": run.model_dump(mode="json")}

    def list_runs(
        self,
        set_version_id: str | None = None,
        actor: ActorContext | None = None,
    ) -> list[dict[str, Any]]:
        if actor:
            self._authorize(actor, "ops.evals.read")
        runs = self._repo.list_runs(set_version_id=set_version_id)
        return [r.model_dump(mode="json") for r in runs]

    def cancel_run(
        self,
        run_id: str,
        reason: str,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        if actor:
            self._authorize(actor, "ops.evals.run")
        run = self._repo.get_run(run_id)
        if not run:
            raise EvaluationNotFoundError(f"Evaluation run {run_id} not found")

        if run.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            return {"run": run.model_dump(mode="json")}

        cancelled_run = run.model_copy(
            update={
                "status": "CANCELLED",
                "cancel_reason": reason,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        state = self._repo.load()
        runs = [r for r in state.runs if r.run_id != run_id]
        runs.append(cancelled_run)
        new_state = state.model_copy(update={"runs": tuple(runs)})

        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="EVAL_RUN",
            entity_id=run_id,
            action="CANCEL_RUN",
            actor_id=actor.user_id if actor else "system",
            actor_role=actor.role if actor else "SYSTEM",
            owner_unit_id=run.owner_unit_id,
            tenant_id=run.tenant_id,
            before={"status": run.status},
            after={"status": "CANCELLED", "cancel_reason": reason},
            reason=reason,
            occurred_at=datetime.now(timezone.utc),
        )
        self._repo.commit_mutation(new_state, audit=audit)
        return {"run": cancelled_run.model_dump(mode="json")}

    def list_case_executions(
        self,
        run_id: str,
        side: TargetSide | None = None,
        actor: ActorContext | None = None,
    ) -> list[dict[str, Any]]:
        if actor:
            self._authorize(actor, "ops.evals.read")
        executions = self._repo.list_case_executions(run_id=run_id, target_side=side)
        return [e.model_dump(mode="json") for e in executions]

    def get_case_execution(
        self,
        execution_id: str,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        if actor:
            self._authorize(actor, "ops.evals.read")
        execution = self._repo.get_case_execution(execution_id)
        if not execution:
            raise EvaluationNotFoundError(f"Case execution {execution_id} not found")
        return {"execution": execution.model_dump(mode="json")}

    def get_trajectory(
        self,
        run_id: str,
        execution_id: str,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        if actor:
            self._authorize(actor, "ops.evals.read")
        execution = self._repo.get_case_execution(execution_id)
        if not execution or execution.run_id != run_id:
            raise EvaluationNotFoundError(f"Case execution {execution_id} not found in run {run_id}")
        trajectory = execution.trace_ref.get("trajectory")
        if not trajectory:
            raise EvaluationNotFoundError(f"No trajectory recorded for execution {execution_id}")
        return {"trajectory": trajectory}

    def review_execution(
        self,
        run_id: str,
        execution_id: str,
        metric_id: str,
        decision: MetricStatus,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        """Appends a human review decision and updates the effective pass determination without mutating raw trace."""
        self._authorize(actor, "ops.evals.results.review")

        execution = self._repo.get_case_execution(execution_id)
        if not execution or execution.run_id != run_id:
            raise EvaluationNotFoundError(f"Execution {execution_id} not found in run {run_id}")

        decision_id = f"rev_dec_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # Locate target metric in execution
        original_metric = next(
            (m for m in execution.metric_results if m.metric_id == metric_id), None
        )
        original_decision = original_metric.pass_status if original_metric else "UNKNOWN"

        review_decision = ReviewDecision(
            decision_id=decision_id,
            run_id=run_id,
            case_execution_id=execution_id,
            metric_id=metric_id,
            original_decision=original_decision,
            new_decision=decision,
            reason=reason,
            reviewer_id=actor.user_id,
            reviewed_at=now,
        )

        # Update the metric result's pass_status
        updated_metrics: list[MetricResult] = []
        for m in execution.metric_results:
            if m.metric_id == metric_id:
                updated_metrics.append(
                    m.model_copy(
                        update={
                            "pass_status": decision,
                            "reason": f"Overridden by human reviewer {actor.user_id}: {reason}",
                        }
                    )
                )
            else:
                updated_metrics.append(m)

        applicable = [m for m in updated_metrics if m.applicability]
        new_passed = all(m.pass_status == "PASS" for m in applicable)

        updated_execution = execution.model_copy(
            update={
                "metric_results": tuple(updated_metrics),
                "passed": new_passed,
                "is_critical_failure": (not new_passed) and execution.is_critical_failure,
            }
        )

        state = self._repo.load()
        existing_executions = [
            e if e.execution_id != execution_id else updated_execution
            for e in state.case_executions
        ]
        decisions = list(state.review_decisions)
        decisions.append(review_decision)

        new_state = state.model_copy(
            update={
                "case_executions": tuple(existing_executions),
                "review_decisions": tuple(decisions),
            }
        )

        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="CASE_EXECUTION",
            entity_id=execution_id,
            action="REVIEW_METRIC",
            actor_id=actor.user_id,
            actor_role=actor.role,
            owner_unit_id="ALL",
            tenant_id=actor.tenant_id or "default",
            before={"metric_id": metric_id, "pass_status": original_decision},
            after={"metric_id": metric_id, "pass_status": decision},
            reason=reason,
            occurred_at=now,
        )
        self._repo.commit_mutation(new_state, audit=audit)
        return {
            "review_decision": review_decision.model_dump(mode="json"),
            "execution": updated_execution.model_dump(mode="json"),
        }

    def rescore_run(
        self,
        run_id: str,
        judge_version: str,
        metric_version: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        """Rescores all completed executions under new judge/metric versions while preserving observations."""
        self._authorize(actor, "ops.evals.results.review")

        run = self._repo.get_run(run_id)
        if not run:
            raise EvaluationNotFoundError(f"Run {run_id} not found")

        # GE2-A08: Baseline and Candidate must use identical judge/metric version
        scorer = EvaluationScorer(version=metric_version)
        state = self._repo.load()
        revision_map = {r.revision_id: r for r in state.revisions}

        updated_executions: list[CaseExecution] = []
        for execution in state.case_executions:
            if execution.run_id != run_id or execution.status != "COMPLETED":
                updated_executions.append(execution)
                continue

            rev = revision_map.get(execution.case_revision_id)
            if not rev:
                updated_executions.append(execution)
                continue

            metric_results, failure_class, passed = scorer.evaluate_execution(
                case_revision=rev,
                answer=execution.answer or "",
                retrieved_evidence=execution.retrieved_evidence,
            )
            is_critical = (not passed) and (rev.criticality == "CRITICAL")
            rescored_exec = execution.model_copy(
                update={
                    "metric_results": metric_results,
                    "failure_classification": failure_class,
                    "passed": passed,
                    "is_critical_failure": is_critical,
                }
            )
            updated_executions.append(rescored_exec)

        # Recompute comparison summary
        rescored_cases = [e for e in updated_executions if e.run_id == run_id]
        total_cost = sum(e.estimated_cost_usd for e in rescored_cases)
        total_cases = len({e.case_revision_id for e in rescored_cases})
        new_summary = self._runner._compute_comparison_summary(
            total_cases=total_cases,
            executed_cases=rescored_cases,
            total_cost=total_cost,
        )

        updated_run = run.model_copy(
            update={
                "judge_version": judge_version,
                "metric_version": metric_version,
                "summary": new_summary,
            }
        )

        runs = [r if r.run_id != run_id else updated_run for r in state.runs]
        new_state = state.model_copy(
            update={
                "runs": tuple(runs),
                "case_executions": tuple(updated_executions),
            }
        )

        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="EVAL_RUN",
            entity_id=run_id,
            action="RESCORE_RUN",
            actor_id=actor.user_id,
            actor_role=actor.role,
            owner_unit_id=run.owner_unit_id,
            tenant_id=run.tenant_id,
            before={"judge_version": run.judge_version, "metric_version": run.metric_version},
            after={"judge_version": judge_version, "metric_version": metric_version},
            reason="Rescored run with updated metric/judge version",
            occurred_at=datetime.now(timezone.utc),
        )
        self._repo.commit_mutation(new_state, audit=audit)
        return {"run": updated_run.model_dump(mode="json")}
