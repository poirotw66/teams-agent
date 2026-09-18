"""Human review overrides and rescoring for evaluation runs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from operations_core.access import ActorContext

from .case_ops import authorize
from .errors import EvaluationNotFoundError
from .models import EvaluationAuditEvent, EvaluationState
from .repository import EvaluationRepository
from .runner import EvaluationRunner
from .runner_models import CaseExecution, MetricResult, MetricStatus, ReviewDecision
from .scorer import EvaluationScorer

__all__ = ["rescore_run", "review_execution"]


def _locate_original_decision(execution: CaseExecution, metric_id: str) -> str:
    original_metric = next(
        (metric for metric in execution.metric_results if metric.metric_id == metric_id),
        None,
    )
    return original_metric.pass_status if original_metric else "UNKNOWN"


def _apply_metric_override(
    execution: CaseExecution,
    *,
    metric_id: str,
    decision: MetricStatus,
    reason: str,
    reviewer_id: str,
) -> tuple[CaseExecution, bool]:
    updated_metrics: list[MetricResult] = []
    for metric in execution.metric_results:
        if metric.metric_id == metric_id:
            updated_metrics.append(
                metric.model_copy(
                    update={
                        "pass_status": decision,
                        "reason": f"Overridden by human reviewer {reviewer_id}: {reason}",
                    }
                )
            )
        else:
            updated_metrics.append(metric)

    applicable = [metric for metric in updated_metrics if metric.applicability]
    new_passed = all(metric.pass_status == "PASS" for metric in applicable)
    updated_execution = execution.model_copy(
        update={
            "metric_results": tuple(updated_metrics),
            "passed": new_passed,
            "is_critical_failure": (not new_passed) and execution.is_critical_failure,
        }
    )
    return updated_execution, new_passed


def review_execution(
    repo: EvaluationRepository,
    *,
    run_id: str,
    execution_id: str,
    metric_id: str,
    decision: MetricStatus,
    reason: str,
    actor: ActorContext,
) -> dict[str, Any]:
    """Append a review decision and update effective pass without mutating raw trace."""
    authorize(actor, "ops.evals.results.review")

    execution = repo.get_case_execution(execution_id)
    if not execution or execution.run_id != run_id:
        raise EvaluationNotFoundError(f"Execution {execution_id} not found in run {run_id}")

    now = datetime.now(timezone.utc)
    original_decision = _locate_original_decision(execution, metric_id)
    review_decision = ReviewDecision(
        decision_id=f"rev_dec_{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        case_execution_id=execution_id,
        metric_id=metric_id,
        original_decision=original_decision,
        new_decision=decision,
        reason=reason,
        reviewer_id=actor.user_id,
        reviewed_at=now,
    )
    updated_execution, _ = _apply_metric_override(
        execution,
        metric_id=metric_id,
        decision=decision,
        reason=reason,
        reviewer_id=actor.user_id,
    )

    state = repo.load()
    existing_executions = [
        item if item.execution_id != execution_id else updated_execution
        for item in state.case_executions
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
    repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return {
        "review_decision": review_decision.model_dump(mode="json"),
        "execution": updated_execution.model_dump(mode="json"),
    }


def _rescore_completed_executions(
    state: EvaluationState,
    *,
    run_id: str,
    metric_version: str,
) -> list[CaseExecution]:
    scorer = EvaluationScorer(version=metric_version)
    revision_map = {revision.revision_id: revision for revision in state.revisions}
    updated_executions: list[CaseExecution] = []

    for execution in state.case_executions:
        if execution.run_id != run_id or execution.status != "COMPLETED":
            updated_executions.append(execution)
            continue
        revision = revision_map.get(execution.case_revision_id)
        if not revision:
            updated_executions.append(execution)
            continue
        metric_results, failure_class, passed = scorer.evaluate_execution(
            case_revision=revision,
            answer=execution.answer or "",
            retrieved_evidence=execution.retrieved_evidence,
        )
        is_critical = (not passed) and (revision.criticality == "CRITICAL")
        updated_executions.append(
            execution.model_copy(
                update={
                    "metric_results": metric_results,
                    "failure_classification": failure_class,
                    "passed": passed,
                    "is_critical_failure": is_critical,
                }
            )
        )
    return updated_executions


def rescore_run(
    repo: EvaluationRepository,
    runner: EvaluationRunner,
    *,
    run_id: str,
    judge_version: str,
    metric_version: str,
    actor: ActorContext,
) -> dict[str, Any]:
    """Rescore completed executions under new judge/metric versions."""
    authorize(actor, "ops.evals.results.review")

    run = repo.get_run(run_id)
    if not run:
        raise EvaluationNotFoundError(f"Run {run_id} not found")

    state = repo.load()
    updated_executions = _rescore_completed_executions(
        state, run_id=run_id, metric_version=metric_version
    )
    rescored_cases = [item for item in updated_executions if item.run_id == run_id]
    total_cost = sum(item.estimated_cost_usd for item in rescored_cases)
    total_cases = len({item.case_revision_id for item in rescored_cases})
    new_summary = runner._compute_comparison_summary(
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
    runs = [item if item.run_id != run_id else updated_run for item in state.runs]
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
    repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return {"run": updated_run.model_dump(mode="json")}
