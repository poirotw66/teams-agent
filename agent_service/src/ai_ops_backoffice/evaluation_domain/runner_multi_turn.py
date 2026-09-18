"""Multi-turn case-side execution for evaluation runs."""

from __future__ import annotations

import time
from typing import Any, Protocol

from .models import CaseRevision, EvaluationCriteria
from .runner_models import (
    CaseExecution,
    MetricResult,
    TargetExecutionInput,
    TargetManifest,
    TargetSide,
)
from .runner_retrieval import (
    evidence_ids,
    persona_context,
    tool_events,
    unpack_answer_result,
)
from .tool_fixture_models import ToolCallTrace, TrajectoryTrace, TurnExecutionTrace

__all__ = ["execute_multi_turn_case"]


class _MultiTurnExecutor(Protocol):
    _scorer: Any
    _agent_scorer: Any
    _answering_fn: Any

    def _retrieve(
        self,
        query: str,
        manifest: TargetManifest,
        execution_input: TargetExecutionInput,
        case_revision: CaseRevision,
    ) -> list[dict[str, Any]]: ...

    def _run_sandbox_turn(
        self,
        query: str,
        manifest: TargetManifest,
        execution_input: TargetExecutionInput,
        *,
        multi_turn_index: int | None = None,
    ) -> tuple[Any, Any, float, list[Any], Any, Any, dict[str, Any]]: ...


def execute_multi_turn_case(
    executor: _MultiTurnExecutor,
    run_id: str,
    case_revision: CaseRevision,
    manifest: TargetManifest,
    side: TargetSide,
    start_time: float,
    *,
    mode: str = "REAL_RAG",
) -> CaseExecution:
    """Execute a multi-turn scenario where agent answers form conversational history."""
    execution_id = f"exec_{run_id[:8]}_{side.lower()}_{case_revision.case_id[:8]}"
    conversation_history: list[dict[str, str]] = []
    turn_traces: list[TurnExecutionTrace] = []
    all_tool_calls: list[ToolCallTrace] = []
    total_tokens = 0
    total_cost = 0.0
    all_retrieved: list[dict[str, Any]] = []
    turn_usage_statuses: list[str] = []

    try:
        for idx, turn in enumerate(case_revision.turns):
            turn_result = _execute_one_turn(
                executor,
                case_revision=case_revision,
                manifest=manifest,
                turn=turn,
                turn_index=idx,
                conversation_history=conversation_history,
                mode=mode,
            )
            all_retrieved.extend(turn_result["retrieved"])
            all_tool_calls.extend(turn_result["tool_calls"])
            total_tokens += turn_result["tokens_delta"]
            total_cost += turn_result["cost"]
            turn_usage_statuses.append(turn_result["usage_status"])
            conversation_history.extend(turn_result["history_delta"])
            turn_traces.append(turn_result["trace"])

        return _build_multi_turn_success(
            executor=executor,
            execution_id=execution_id,
            run_id=run_id,
            case_revision=case_revision,
            side=side,
            start_time=start_time,
            turn_traces=turn_traces,
            all_retrieved=all_retrieved,
            all_tool_calls=all_tool_calls,
            conversation_history=conversation_history,
            total_tokens=total_tokens,
            total_cost=total_cost,
            turn_usage_statuses=turn_usage_statuses,
        )
    except Exception as e:
        return _build_multi_turn_failure(
            executor=executor,
            execution_id=execution_id,
            run_id=run_id,
            case_revision=case_revision,
            side=side,
            start_time=start_time,
            error=e,
        )


def _execute_one_turn(
    executor: _MultiTurnExecutor,
    *,
    case_revision: CaseRevision,
    manifest: TargetManifest,
    turn: Any,
    turn_index: int,
    conversation_history: list[dict[str, str]],
    mode: str,
) -> dict[str, Any]:
    user_query = turn.user_query
    turn_input = TargetExecutionInput(
        query=user_query,
        conversation_history=tuple(conversation_history),
        persona_context=persona_context(manifest),
        actor_id=manifest.target_id,
        tenant_id="default",
        owner_unit_id="default",
        environment=manifest.environment,
        case_id=case_revision.case_id,
    )
    retrieved = executor._retrieve(user_query, manifest, turn_input, case_revision)
    answer, tokens, cost, tool_calls, turn_usage = _answer_turn(
        executor,
        user_query=user_query,
        manifest=manifest,
        turn_input=turn_input,
        retrieved=retrieved,
        conversation_history=conversation_history,
        mode=mode,
        turn_index=turn_index,
    )
    tokens_delta = tokens if tokens is not None else 0
    if tokens is None or str(tokens).upper() == "UNKNOWN":
        usage_status = "UNKNOWN"
    else:
        usage_status = str(turn_usage).upper() if turn_usage else "EXACT"

    # Mandatory GE3 rule: Expected answer is NEVER used as assistant history.
    history_delta = [
        {"role": "user", "content": user_query},
        {"role": "assistant", "content": answer},
    ]
    turn_rev = case_revision.model_copy(
        update={
            "query": user_query,
            "criteria": turn.criteria or EvaluationCriteria(),
            "evidence": turn.evidence,
            "behavior": turn.expected_behavior,
        }
    )
    t_metrics, _, _ = executor._scorer.evaluate_execution(
        case_revision=turn_rev,
        answer=answer,
        retrieved_evidence=tuple(retrieved),
    )
    turn_passed = all(m.pass_status == "PASS" for m in t_metrics if m.applicability)
    trace = TurnExecutionTrace(
        turn_index=turn_index,
        turn_id=turn.turn_id,
        user_query=user_query,
        agent_response=answer,
        tool_calls=tuple(tool_calls),
        metrics=tuple(t_metrics),
        passed=turn_passed,
    )
    return {
        "retrieved": retrieved,
        "tool_calls": tool_calls,
        "tokens_delta": tokens_delta,
        "cost": cost,
        "usage_status": usage_status,
        "history_delta": history_delta,
        "trace": trace,
    }


def _answer_turn(
    executor: _MultiTurnExecutor,
    *,
    user_query: str,
    manifest: TargetManifest,
    turn_input: TargetExecutionInput,
    retrieved: list[dict[str, Any]],
    conversation_history: list[dict[str, str]],
    mode: str,
    turn_index: int,
) -> tuple[Any, Any, float, list[Any], Any]:
    if mode == "AGENT_SANDBOX":
        answer, tokens, cost, tool_calls, _, turn_usage, _ = executor._run_sandbox_turn(
            user_query,
            manifest,
            turn_input,
            multi_turn_index=turn_index,
        )
        return answer, tokens, cost, tool_calls, turn_usage
    if executor._answering_fn:
        ans_res = executor._answering_fn(
            user_query,
            manifest,
            turn_input,
            retrieved,
            conversation_history,
        )
        answer, tokens, cost, tool_calls, _, turn_usage = unpack_answer_result(ans_res)
        return answer, tokens, cost, tool_calls, turn_usage
    return f"Turn {turn_index + 1} response to '{user_query}'", 120, 0.00004, [], None


def _build_multi_turn_success(
    *,
    executor: _MultiTurnExecutor,
    execution_id: str,
    run_id: str,
    case_revision: CaseRevision,
    side: TargetSide,
    start_time: float,
    turn_traces: list[TurnExecutionTrace],
    all_retrieved: list[dict[str, Any]],
    all_tool_calls: list[ToolCallTrace],
    conversation_history: list[dict[str, str]],
    total_tokens: int,
    total_cost: float,
    turn_usage_statuses: list[str],
) -> CaseExecution:
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    trajectory_metrics, failed_idx, failed_reason, traj_passed = (
        executor._agent_scorer.score_trajectory_timeline(
            case_revision=case_revision,
            turns=tuple(turn_traces),
        )
    )
    case_metrics, failure_class = _score_case_level_metrics(executor, case_revision, turn_traces)
    overall_passed = traj_passed and all(
        m.pass_status == "PASS" for m in case_metrics if m.applicability
    )
    if not overall_passed and failure_class is None:
        failure_class = "ANSWER_INCORRECT"

    trajectory = TrajectoryTrace(
        execution_id=execution_id,
        case_id=case_revision.case_id,
        target_side=side,
        turns=tuple(turn_traces),
        failed_step_index=failed_idx,
        failed_step_reason=failed_reason,
        overall_passed=overall_passed,
    )
    return CaseExecution(
        execution_id=execution_id,
        run_id=run_id,
        case_revision_id=case_revision.revision_id,
        case_id=case_revision.case_id,
        target_side=side,
        attempt=1,
        status="COMPLETED",
        answer=turn_traces[-1].agent_response if turn_traces else "",
        retrieved_evidence=tuple(all_retrieved),
        trace_ref={
            "trajectory": trajectory.model_dump(mode="json"),
            "conversation_history": conversation_history,
        },
        metric_results=tuple(list(case_metrics) + list(trajectory_metrics)),
        failure_classification=failure_class,
        passed=overall_passed,
        is_critical_failure=(not overall_passed) and (case_revision.criticality == "CRITICAL"),
        used_tokens=total_tokens,
        actual_tokens=total_tokens,
        usage_status=_aggregate_usage_status(turn_usage_statuses),
        latency_ms=duration_ms,
        estimated_cost_usd=round(total_cost, 6),
        evidence_ids=evidence_ids(all_retrieved),
        tool_events=tool_events(all_tool_calls),
    )


def _score_case_level_metrics(
    executor: _MultiTurnExecutor,
    case_revision: CaseRevision,
    turn_traces: list[TurnExecutionTrace],
) -> tuple[list[MetricResult], str | None]:
    case_metrics: list[MetricResult] = []
    failure_class = None
    combined_answers = " \n".join(t.agent_response for t in turn_traces)
    if case_revision.criteria.forbidden_claims:
        fc_metric = executor._scorer.score_forbidden_claims(case_revision, combined_answers)
        case_metrics.append(fc_metric)
        if fc_metric.pass_status == "FAIL":
            failure_class = "SAFETY_VIOLATION"
    if case_revision.criteria.required_facts:
        rf_metric = executor._scorer.score_required_facts(case_revision, combined_answers)
        case_metrics.append(rf_metric)
        if rf_metric.pass_status == "FAIL" and failure_class is None:
            failure_class = "ANSWER_INCORRECT"
    return case_metrics, failure_class


def _aggregate_usage_status(turn_usage_statuses: list[str]) -> str:
    if any(s == "UNKNOWN" for s in turn_usage_statuses):
        return "UNKNOWN"
    if any(s == "ESTIMATED" for s in turn_usage_statuses):
        return "ESTIMATED"
    return "EXACT"


def _build_multi_turn_failure(
    *,
    executor: _MultiTurnExecutor,
    execution_id: str,
    run_id: str,
    case_revision: CaseRevision,
    side: TargetSide,
    start_time: float,
    error: Exception,
) -> CaseExecution:
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    metric_results, failure_class, _ = executor._scorer.evaluate_execution(
        case_revision=case_revision,
        answer="",
        retrieved_evidence=(),
        error_message=str(error),
    )
    return CaseExecution(
        execution_id=execution_id,
        run_id=run_id,
        case_revision_id=case_revision.revision_id,
        case_id=case_revision.case_id,
        target_side=side,
        attempt=1,
        status="FAILED",
        metric_results=metric_results,
        failure_classification=failure_class,
        passed=False,
        is_critical_failure=case_revision.criticality == "CRITICAL",
        latency_ms=duration_ms,
    )
