"""Helpers for EvaluationRunner.execute_run orchestration."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .errors import EvaluationVersionConflictError
from .models import CaseRevision, EvaluationAuditEvent
from .repository import EvaluationRepository
from .runner_models import (
    CaseExecution,
    EvaluationRun,
    RunComparisonSummary,
    TargetManifest,
    TargetSide,
)

logger = logging.getLogger(__name__)

_CAS_MAX_ATTEMPTS = 3

ExecuteOrResumeSide = Callable[..., CaseExecution]
ComputeSummary = Callable[..., RunComparisonSummary]
CheckLease = Callable[[], None]


def resolve_case_revisions(
    *,
    state: Any,
    set_version: Any,
    max_cases: Any,
) -> list[CaseRevision]:
    revision_map = {r.revision_id: r for r in state.revisions}
    case_revisions: list[CaseRevision] = []
    for r_id in set_version.case_revision_ids:
        if r_id in revision_map:
            case_revisions.append(revision_map[r_id])
    if max_cases:
        case_revisions = case_revisions[:max_cases]
    return case_revisions


def execute_case_loop(
    *,
    run: EvaluationRun,
    run_id: str,
    case_revisions: list[CaseRevision],
    completed_sides: dict[tuple[str, str], CaseExecution],
    max_tokens: float,
    max_cost_usd: float,
    repo: EvaluationRepository,
    execute_or_resume_side: ExecuteOrResumeSide,
) -> tuple[list[CaseExecution], int, float, str | None]:
    executed_cases: list[CaseExecution] = []
    total_tokens = 0
    total_cost = 0.0
    cancel_reason = None

    for revision in case_revisions:
        fresh_run = repo.get_run(run_id)
        if fresh_run and fresh_run.status in {"CANCELLING", "CANCELLED"}:
            cancel_reason = fresh_run.cancel_reason or "User cancelled run"
            break

        if total_tokens >= max_tokens or total_cost >= max_cost_usd:
            cancel_reason = "Budget limit reached: max_cost_usd or max_tokens exceeded"
            break

        for side, manifest in (
            ("BASELINE", run.baseline_manifest),
            ("CANDIDATE", run.candidate_manifest),
        ):
            execution = execute_or_resume_side(
                run=run,
                revision=revision,
                side=side,
                manifest=manifest,
                completed_sides=completed_sides,
            )
            executed_cases.append(execution)
            total_tokens += execution.used_tokens
            total_cost += execution.estimated_cost_usd

    return executed_cases, total_tokens, total_cost, cancel_reason


def build_final_run(
    *,
    run: EvaluationRun,
    executed_cases: list[CaseExecution],
    total_tokens: int,
    total_cost: float,
    cancel_reason: str | None,
    case_revision_count: int,
    compute_comparison_summary: ComputeSummary,
) -> EvaluationRun:
    summary = compute_comparison_summary(
        total_cases=case_revision_count,
        executed_cases=executed_cases,
        total_cost=total_cost,
    )
    completed_at = datetime.now(timezone.utc)
    final_status = "CANCELLED" if cancel_reason else "COMPLETED"
    has_unknown_tokens = any(e.usage_status == "UNKNOWN" for e in executed_cases)
    cost_status = "PARTIAL_UNKNOWN" if has_unknown_tokens else "EXACT"
    return run.model_copy(
        update={
            "status": final_status,
            "completed_at": completed_at,
            "summary": summary,
            "cancel_reason": cancel_reason,
            "actual_cost_usd": round(total_cost, 4),
            "actual_tokens": total_tokens,
            "cost_status": cost_status,
            "is_eval_eligible": run.mode != "OFFLINE_BENCHMARK",
        }
    )


def commit_run_completion(
    *,
    repo: EvaluationRepository,
    run: EvaluationRun,
    run_id: str,
    final_run: EvaluationRun,
    executed_cases: list[CaseExecution],
    total_cost: float,
    cancel_reason: str | None,
    check_lease: CheckLease,
) -> EvaluationRun:
    last_conflict: EvaluationVersionConflictError | None = None
    completed_at = final_run.completed_at or datetime.now(timezone.utc)
    final_status = final_run.status
    for attempt in range(_CAS_MAX_ATTEMPTS):
        check_lease()
        current_state = repo.load()
        runs = [r for r in current_state.runs if r.run_id != run_id]
        runs.append(final_run)
        other_executions = [e for e in current_state.case_executions if e.run_id != run_id]
        new_state = current_state.model_copy(
            update={
                "runs": tuple(runs),
                "case_executions": tuple(other_executions + executed_cases),
            }
        )
        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="EVAL_RUN",
            entity_id=run_id,
            action="RUN_COMPLETED" if final_status == "COMPLETED" else "RUN_CANCELLED",
            actor_id=run.requested_by,
            actor_role="SYSTEM",
            owner_unit_id=run.owner_unit_id,
            tenant_id=run.tenant_id,
            before={"status": run.status},
            after={"status": final_status, "actual_cost_usd": total_cost},
            reason=cancel_reason or "Evaluation run finished successfully",
            occurred_at=completed_at,
            correlation_id=run.correlation_id,
        )
        try:
            repo.commit_mutation(new_state, audit=audit, expected_revision=current_state.revision)
            return final_run
        except EvaluationVersionConflictError as exc:
            last_conflict = exc
            logger.warning(
                "CAS conflict completing run %s (attempt %s/%s)",
                run_id,
                attempt + 1,
                _CAS_MAX_ATTEMPTS,
            )
    assert last_conflict is not None
    raise last_conflict


# Re-export types used by callers that import from this module.
__all__ = [
    "TargetManifest",
    "TargetSide",
    "build_final_run",
    "commit_run_completion",
    "execute_case_loop",
    "resolve_case_revisions",
]
