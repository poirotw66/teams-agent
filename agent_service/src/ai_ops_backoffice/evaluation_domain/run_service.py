"""Evaluation run lifecycle facade: preflight, create, cancel, review, rescore."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from operations_core.access import ActorContext

from . import run_create_ops, run_outbox_ops, run_review_ops
from .case_ops import authorize
from .errors import EvaluationNotFoundError
from .job_repository import JobRepository
from .manifest import ManifestResolver
from .models import EvaluationAuditEvent
from .repository import EvaluationRepository
from .runner import EvaluationRunner
from .runner_models import MetricStatus, RunPreflightResult, TargetSide
from .scorer import EvaluationScorer

__all__ = ["EvaluationRunService"]


class EvaluationRunService:
    """Manages lifecycle, preflight, dispatch, review, and rescoring of Evaluation Runs."""

    def __init__(
        self,
        repository: EvaluationRepository,
        manifest_resolver: ManifestResolver | None = None,
        runner: EvaluationRunner | None = None,
        scorer: EvaluationScorer | None = None,
        job_repository: JobRepository | None = None,
    ) -> None:
        self._repo = repository
        self._resolver = manifest_resolver or ManifestResolver(repository)
        self._scorer = scorer or EvaluationScorer()
        self._runner = runner or EvaluationRunner(repository, scorer=self._scorer)
        self._job_repo = job_repository

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str | None = None) -> None:
        authorize(actor, capability, owner_unit_id)

    def preflight_run(
        self,
        set_version_id: str,
        baseline_target: dict[str, Any],
        candidate_target: dict[str, Any],
        limits: dict[str, Any] | None = None,
        actor: ActorContext | None = None,
        mode: str = "REAL_RAG",
    ) -> RunPreflightResult:
        return run_create_ops.preflight_run(
            self._runner,
            self._resolver,
            set_version_id=set_version_id,
            baseline_target=baseline_target,
            candidate_target=candidate_target,
            limits=limits,
            actor=actor,
            mode=mode,
        )

    def has_job_repository(self) -> bool:
        return self._job_repo is not None

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
        execute_inline: bool | None = None,
    ) -> dict[str, Any]:
        """Queues and executes an evaluation run."""
        return run_create_ops.create_run(
            self._repo,
            self._resolver,
            self._runner,
            self._job_repo,
            set_version_id=set_version_id,
            baseline_target=baseline_target,
            candidate_target=candidate_target,
            mode=mode,
            limits=limits,
            repetitions=repetitions,
            quality_case_id=quality_case_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            actor=actor,
            execute_inline=execute_inline,
        )

    def _dispatch_outbox_job(self, outbox_entry: dict[str, Any]) -> bool:
        return run_outbox_ops.dispatch_outbox_job(self._job_repo, outbox_entry)

    def _remove_outbox_job(self, outbox_id: str) -> None:
        run_outbox_ops.remove_outbox_job(self._repo, outbox_id)

    def _mark_run_enqueue_failed(
        self,
        run_id: str,
        error: str,
        *,
        actor: ActorContext | None = None,
    ) -> None:
        _ = actor  # retained for call-site compatibility
        run_outbox_ops.mark_run_enqueue_failed(self._repo, run_id, error)

    def recover_undispatched_runs(self, *, older_than_seconds: float = 30.0) -> int:
        """Process pending outbox jobs and recover queued runs missing durable jobs."""
        return run_outbox_ops.recover_undispatched_runs(
            self._repo,
            self._job_repo,
            older_than_seconds=older_than_seconds,
        )

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
        tenant = actor.tenant_id if actor else None
        runs = self._repo.list_runs(set_version_id=set_version_id, tenant_id=tenant)
        return [item.model_dump(mode="json") for item in runs]

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

        if self._job_repo:
            job = self._job_repo.get_job_by_run_id(run_id)
            if job:
                self._job_repo.request_cancellation(job.job_id)

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
        runs = [item for item in state.runs if item.run_id != run_id]
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
        self._repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
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
        return [item.model_dump(mode="json") for item in executions]

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
            raise EvaluationNotFoundError(
                f"Case execution {execution_id} not found in run {run_id}"
            )
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
        """Appends a human review decision and updates the effective pass determination."""
        return run_review_ops.review_execution(
            self._repo,
            run_id=run_id,
            execution_id=execution_id,
            metric_id=metric_id,
            decision=decision,
            reason=reason,
            actor=actor,
        )

    def rescore_run(
        self,
        run_id: str,
        judge_version: str,
        metric_version: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        """Rescores all completed executions under new judge/metric versions."""
        return run_review_ops.rescore_run(
            self._repo,
            self._runner,
            run_id=run_id,
            judge_version=judge_version,
            metric_version=metric_version,
            actor=actor,
        )
