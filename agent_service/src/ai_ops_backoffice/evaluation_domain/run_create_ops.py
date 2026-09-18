"""Create and queue evaluation runs (inline or via durable outbox)."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from operations_core.access import ActorContext

from . import run_outbox_ops
from .case_ops import authorize
from .errors import (
    EvaluationNotFoundError,
    EvaluationValidationError,
    EvaluationVersionConflictError,
)
from .job_repository import JobRepository
from .manifest import ManifestResolver
from .models import EvaluationAuditEvent
from .repository import EvaluationRepository
from .runner import EvaluationRunner
from .runner_models import EvaluationRun, RunPreflightResult

logger = logging.getLogger(__name__)

__all__ = [
    "adapter_capabilities",
    "create_run",
    "preflight_run",
]


def adapter_capabilities(runner: EvaluationRunner) -> tuple[bool, bool, bool]:
    has_retriever = (
        runner.has_retriever_adapter() if hasattr(runner, "has_retriever_adapter") else True
    )
    has_answering = (
        runner.has_answering_adapter() if hasattr(runner, "has_answering_adapter") else True
    )
    has_sandbox = runner.has_sandbox_adapter() if hasattr(runner, "has_sandbox_adapter") else True
    return has_retriever, has_answering, has_sandbox


def preflight_run(
    runner: EvaluationRunner,
    resolver: ManifestResolver,
    *,
    set_version_id: str,
    baseline_target: dict[str, Any],
    candidate_target: dict[str, Any],
    limits: dict[str, Any] | None = None,
    actor: ActorContext | None = None,
    mode: str = "REAL_RAG",
) -> RunPreflightResult:
    if actor:
        authorize(actor, "ops.evals.read")
    has_retriever, has_answering, has_sandbox = adapter_capabilities(runner)
    return resolver.preflight_run(
        set_version_id=set_version_id,
        baseline_target=baseline_target,
        candidate_target=candidate_target,
        limits=limits,
        mode=mode,
        has_retriever_adapter=has_retriever,
        has_answering_adapter=has_answering,
        has_sandbox_adapter=has_sandbox,
    )


def _validate_preflight(
    runner: EvaluationRunner,
    resolver: ManifestResolver,
    *,
    set_version_id: str,
    baseline_target: dict[str, Any],
    candidate_target: dict[str, Any],
    limits: dict[str, Any],
    mode: str,
) -> RunPreflightResult:
    has_retriever, has_answering, has_sandbox = adapter_capabilities(runner)
    preflight = resolver.preflight_run(
        set_version_id=set_version_id,
        baseline_target=baseline_target,
        candidate_target=candidate_target,
        limits=limits,
        mode=mode,
        has_retriever_adapter=has_retriever,
        has_answering_adapter=has_answering,
        has_sandbox_adapter=has_sandbox,
    )
    if not preflight.is_valid:
        raise EvaluationValidationError(
            f"Run preflight rejected with errors: {'; '.join(preflight.blocking_errors)}"
        )
    return preflight


def _build_queued_run(
    repo: EvaluationRepository,
    *,
    set_version_id: str,
    preflight: RunPreflightResult,
    mode: str,
    limits: dict[str, Any],
    repetitions: int,
    quality_case_id: str | None,
    correlation_id: str | None,
    actor: ActorContext | None,
) -> EvaluationRun:
    set_version = repo.get_set_version(set_version_id)
    if not set_version:
        raise EvaluationNotFoundError(f"Set version {set_version_id} not found")

    eval_set = repo.get_set(set_version.set_id)
    owner_unit = eval_set.owner_unit_ids[0] if eval_set and eval_set.owner_unit_ids else "ALL"
    tenant_id = eval_set.tenant_id if eval_set else "default"
    now = datetime.now(timezone.utc)

    return EvaluationRun(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
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
        is_eval_eligible=preflight.is_eval_eligible,
    )


def _build_outbox_entry(
    run: EvaluationRun,
    *,
    should_execute_inline: bool,
    job_repo: JobRepository | None,
) -> dict[str, Any] | None:
    if should_execute_inline or not job_repo:
        return None
    job_id = str(uuid.uuid4())
    return {
        "outbox_id": f"outbox_{job_id}",
        "job_id": job_id,
        "run_id": run.run_id,
        "tenant_id": run.tenant_id,
        "logical_key": f"run:{run.tenant_id}:{run.run_id}",
        "state": "QUEUED",
        "created_at": run.created_at.isoformat(),
        "attempts": 0,
    }


def _commit_queued_run(
    repo: EvaluationRepository,
    run: EvaluationRun,
    outbox_entry: dict[str, Any] | None,
    *,
    actor: ActorContext | None,
    correlation_id: str | None,
) -> None:
    max_retries = 5
    for attempt in range(max_retries):
        state = repo.load()
        runs = list(state.runs)
        runs.append(run)
        new_outbox = list(getattr(state, "outbox_jobs", ()))
        if outbox_entry is not None:
            new_outbox.append(outbox_entry)
        new_state = state.model_copy(update={"runs": tuple(runs), "outbox_jobs": tuple(new_outbox)})
        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="EVAL_RUN",
            entity_id=run.run_id,
            action="CREATE_RUN",
            actor_id=actor.user_id if actor else "system",
            actor_role=actor.role if actor else "SYSTEM",
            owner_unit_id=run.owner_unit_id,
            tenant_id=run.tenant_id,
            before=None,
            after={"run_id": run.run_id, "status": "QUEUED"},
            reason="Queued new evaluation run",
            occurred_at=run.created_at,
            correlation_id=correlation_id,
        )
        try:
            repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
            return
        except EvaluationVersionConflictError:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.02 * (attempt + 1))


def _execute_or_dispatch(
    runner: EvaluationRunner,
    repo: EvaluationRepository,
    job_repo: JobRepository | None,
    run: EvaluationRun,
    *,
    should_execute_inline: bool,
    outbox_entry: dict[str, Any] | None,
) -> EvaluationRun:
    if should_execute_inline:
        return runner.execute_run(run.run_id)
    if job_repo and outbox_entry:
        try:
            dispatched = run_outbox_ops.dispatch_outbox_job(job_repo, outbox_entry)
            if dispatched:
                run_outbox_ops.remove_outbox_job(repo, outbox_entry["outbox_id"])
        except Exception as err:
            logger.debug("Immediate outbox dispatch failed: %s", err)
    return run


def create_run(
    repo: EvaluationRepository,
    resolver: ManifestResolver,
    runner: EvaluationRunner,
    job_repo: JobRepository | None,
    *,
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
    _ = idempotency_key  # reserved for future idempotent create semantics
    if actor:
        authorize(actor, "ops.evals.run")

    limits = limits or {}
    preflight = _validate_preflight(
        runner,
        resolver,
        set_version_id=set_version_id,
        baseline_target=baseline_target,
        candidate_target=candidate_target,
        limits=limits,
        mode=mode,
    )
    run = _build_queued_run(
        repo,
        set_version_id=set_version_id,
        preflight=preflight,
        mode=mode,
        limits=limits,
        repetitions=repetitions,
        quality_case_id=quality_case_id,
        correlation_id=correlation_id,
        actor=actor,
    )
    should_execute_inline = execute_inline if execute_inline is not None else (job_repo is None)
    outbox_entry = _build_outbox_entry(
        run, should_execute_inline=should_execute_inline, job_repo=job_repo
    )
    _commit_queued_run(
        repo,
        run,
        outbox_entry,
        actor=actor,
        correlation_id=correlation_id,
    )
    run = _execute_or_dispatch(
        runner,
        repo,
        job_repo,
        run,
        should_execute_inline=should_execute_inline,
        outbox_entry=outbox_entry,
    )
    return {
        "run": run.model_dump(mode="json"),
        "runId": run.run_id,
        "statusUrl": f"/api/evaluations/runs/{run.run_id}",
    }
