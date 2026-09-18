"""Single-case side execution for evaluation runs (single-turn and multi-turn)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .agent_behavior_scorer import AgentBehaviorScorer
from .errors import EvaluationValidationError
from .models import CaseRevision
from .runner_models import (
    CaseExecution,
    MetricResult,
    TargetExecutionInput,
    TargetManifest,
    TargetSide,
)
from .runner_retrieval import (
    default_knowledge_retriever,
    evidence_ids,
    normalize_token_usage,
    persona_context,
    tool_events,
    unpack_answer_result,
)
from .scorer import EvaluationScorer
from .tool_fixture_models import ToolCallTrace

__all__ = [
    "CaseSideExecutor",
    "default_knowledge_retriever",
    "evidence_ids",
    "normalize_token_usage",
    "persona_context",
    "tool_events",
    "unpack_answer_result",
]


class CaseSideExecutor:
    """Runs baseline/candidate execution for one case revision (single or multi-turn)."""

    def __init__(
        self,
        *,
        scorer: EvaluationScorer,
        agent_scorer: AgentBehaviorScorer,
        retriever_fn: Any | None = None,
        answering_fn: Any | None = None,
        sandbox_adapter: Any | None = None,
        releases_dir: Path | None = None,
    ) -> None:
        self._scorer = scorer
        self._agent_scorer = agent_scorer
        self._retriever_fn = retriever_fn
        self._answering_fn = answering_fn
        self._sandbox_adapter = sandbox_adapter
        self._releases_dir = releases_dir

    def execute_side(
        self,
        run_id: str,
        case_revision: CaseRevision,
        manifest: TargetManifest,
        side: TargetSide,
        mode: str = "REAL_RAG",
    ) -> CaseExecution:
        """Execute a single side (baseline or candidate) for a case revision."""
        execution_id = f"exec_{run_id[:8]}_{side.lower()}_{case_revision.case_id[:8]}"
        start_time = time.perf_counter()

        if case_revision.turns:
            return self.execute_multi_turn(
                run_id,
                case_revision,
                manifest,
                side,
                start_time,
                mode=mode,
            )

        try:
            return self._execute_single_turn(
                execution_id=execution_id,
                run_id=run_id,
                case_revision=case_revision,
                manifest=manifest,
                side=side,
                mode=mode,
                start_time=start_time,
            )
        except Exception as e:
            return self._build_failed_side_execution(
                execution_id=execution_id,
                run_id=run_id,
                case_revision=case_revision,
                side=side,
                start_time=start_time,
                error=e,
            )

    def _execute_single_turn(
        self,
        *,
        execution_id: str,
        run_id: str,
        case_revision: CaseRevision,
        manifest: TargetManifest,
        side: TargetSide,
        mode: str,
        start_time: float,
    ) -> CaseExecution:
        # F01-T3: Strictly sanitize input to target under test - never pass golden answers or criteria
        sanitized_input = TargetExecutionInput(
            query=case_revision.query,
            conversation_history=(),
            persona_context=persona_context(manifest),
            actor_id=manifest.target_id,
            tenant_id="default",
            owner_unit_id="default",
            environment=manifest.environment,
            case_id=case_revision.case_id,
        )
        retrieved = self._retrieve(case_revision.query, manifest, sanitized_input, case_revision)
        answer, tokens, cost, tool_calls, provider_req_id, upstream_usage_status, sandbox_trace = (
            self._produce_single_turn_answer(
                case_revision=case_revision,
                manifest=manifest,
                sanitized_input=sanitized_input,
                retrieved=retrieved,
                mode=mode,
            )
        )
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        actual_tokens, used_tokens, usage_status = normalize_token_usage(
            tokens, upstream_usage_status
        )
        events = tool_events(tool_calls)
        metric_results, failure_class, passed = self._scorer.evaluate_execution(
            case_revision=case_revision,
            answer=answer,
            retrieved_evidence=tuple(retrieved),
        )
        metric_results, failure_class, passed = self._apply_tool_constraint_scoring(
            case_revision,
            tool_calls,
            metric_results,
            failure_class,
            passed,
        )
        trace_ref: dict[str, Any] = {}
        if tool_calls:
            trace_ref["tool_calls"] = list(events)
        if sandbox_trace is not None:
            trace_ref["sandbox"] = sandbox_trace
        return CaseExecution(
            execution_id=execution_id,
            run_id=run_id,
            case_revision_id=case_revision.revision_id,
            case_id=case_revision.case_id,
            target_side=side,
            attempt=1,
            status="COMPLETED",
            answer=answer,
            retrieved_evidence=tuple(retrieved),
            trace_ref=trace_ref,
            metric_results=metric_results,
            failure_classification=failure_class,
            passed=passed,
            is_critical_failure=(not passed) and (case_revision.criticality == "CRITICAL"),
            used_tokens=used_tokens,
            actual_tokens=actual_tokens,
            usage_status=usage_status,
            latency_ms=duration_ms,
            estimated_cost_usd=cost,
            evidence_ids=evidence_ids(retrieved),
            provider_request_id=provider_req_id,
            tool_events=events,
        )

    def _produce_single_turn_answer(
        self,
        *,
        case_revision: CaseRevision,
        manifest: TargetManifest,
        sanitized_input: TargetExecutionInput,
        retrieved: list[dict[str, Any]],
        mode: str,
    ) -> tuple[Any, Any, float, list[Any], Any, Any, dict[str, Any] | None]:
        if mode == "AGENT_SANDBOX":
            return self._run_sandbox_turn(case_revision.query, manifest, sanitized_input)
        if self._answering_fn:
            ans_res = self._answering_fn(
                case_revision.query,
                manifest,
                sanitized_input,
                retrieved,
            )
            answer, tokens, cost, tool_calls, provider_req_id, upstream_usage_status = (
                unpack_answer_result(ans_res)
            )
            return (
                answer,
                tokens,
                cost,
                tool_calls,
                provider_req_id,
                upstream_usage_status,
                None,
            )
        # Default mock answer fallback
        answer = f"這是針對「{case_revision.query}」的依據回覆 [來源: {manifest.target_id}]"
        return answer, 150, 0.00005, [], None, None, None

    def _build_failed_side_execution(
        self,
        *,
        execution_id: str,
        run_id: str,
        case_revision: CaseRevision,
        side: TargetSide,
        start_time: float,
        error: Exception,
    ) -> CaseExecution:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        metric_results, failure_class, _passed = self._scorer.evaluate_execution(
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
            error_detail=str(error),
        )

    def execute_multi_turn(
        self,
        run_id: str,
        case_revision: CaseRevision,
        manifest: TargetManifest,
        side: TargetSide,
        start_time: float,
        *,
        mode: str = "REAL_RAG",
    ) -> CaseExecution:
        """Delegate multi-turn execution to the dedicated stage module."""
        from .runner_multi_turn import execute_multi_turn_case

        return execute_multi_turn_case(
            self,
            run_id,
            case_revision,
            manifest,
            side,
            start_time,
            mode=mode,
        )

    def _retrieve(
        self,
        query: str,
        manifest: TargetManifest,
        execution_input: TargetExecutionInput,
        case_revision: CaseRevision,
    ) -> list[dict[str, Any]]:
        if self._retriever_fn:
            return self._retriever_fn(query, manifest, execution_input)
        return default_knowledge_retriever(query, manifest, case_revision, self._releases_dir)

    def _run_sandbox_turn(
        self,
        query: str,
        manifest: TargetManifest,
        execution_input: TargetExecutionInput,
        *,
        multi_turn_index: int | None = None,
    ) -> tuple[Any, Any, float, list[Any], Any, Any, dict[str, Any]]:
        if self._sandbox_adapter is None:
            raise EvaluationValidationError(
                "AGENT_SANDBOX execution rejected: Missing registered formal Agent workflow adapter."
            )
        workflow_result = self._sandbox_adapter.execute_workflow_turn(
            query, manifest, execution_input
        )
        if not isinstance(workflow_result, dict):
            raise EvaluationValidationError(
                "AGENT_SANDBOX execution rejected: workflow executor must return "
                "a structured result with answer and tool_calls."
            )
        sandbox_trace = dict(workflow_result)
        answer = str(workflow_result.get("answer") or "").strip()
        status = str(workflow_result.get("status") or "").upper()
        if status in {"FAILED", "UNAVAILABLE"} or not answer:
            if multi_turn_index is None:
                raise EvaluationValidationError(
                    "AGENT_SANDBOX execution rejected: workflow did not return "
                    "a real answer from AgentWorkflow execution "
                    f"(status={status or 'missing'})."
                )
            raise EvaluationValidationError(
                "AGENT_SANDBOX multi-turn rejected: workflow did not return "
                f"a real answer (status={status or 'missing'}, turn={multi_turn_index})."
            )
        tokens = workflow_result.get("tokens", 0)
        cost = float(workflow_result.get("cost_usd") or 0.0)
        tool_calls = list(workflow_result.get("tool_calls") or [])
        provider_req_id = workflow_result.get("provider_request_id")
        upstream_usage_status = workflow_result.get("usage_status")
        return (
            answer,
            tokens,
            cost,
            tool_calls,
            provider_req_id,
            upstream_usage_status,
            sandbox_trace,
        )

    def _apply_tool_constraint_scoring(
        self,
        case_revision: CaseRevision,
        tool_calls: list[ToolCallTrace],
        metric_results: tuple[MetricResult, ...],
        failure_class: str | None,
        passed: bool,
    ) -> tuple[tuple[MetricResult, ...], str | None, bool]:
        tc = case_revision.tool_constraints
        if not tc or not (
            tc.required_tools
            or tc.forbidden_tools
            or tc.allowed_tools
            or tc.parameter_constraints
            or tc.tool_order
            or tc.allowed_paths
            or tool_calls
        ):
            return metric_results, failure_class, passed

        tool_metrics = self._agent_scorer.score_tool_constraints(tc, tuple(tool_calls))
        metric_results = metric_results + tuple(tool_metrics)
        for tm in tool_metrics:
            if tm.applicability and tm.pass_status == "FAIL":
                passed = False
                if tm.metric_id == "tool.forbidden_tools":
                    failure_class = "SAFETY_VIOLATION"
                elif failure_class is None:
                    failure_class = "ANSWER_INCORRECT"
        return metric_results, failure_class, passed
