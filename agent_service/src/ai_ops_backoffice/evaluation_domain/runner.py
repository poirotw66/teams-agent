from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CaseRevision
from .runner_models import TargetManifest


def default_knowledge_retriever(
    query: str,
    manifest: TargetManifest,
    case_revision: CaseRevision,
    releases_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Default retriever loading from pinned knowledge release chunks.json if available."""
    if not manifest.knowledge_release_id or not releases_dir:
        return []

    index_path = releases_dir / manifest.knowledge_release_id / "index" / "chunks.json"
    if not index_path.is_file():
        return []

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        chunks = data.get("chunks", [])
    except Exception as e:
        logger.warning("Failed to load chunks from %s: %s", index_path, e)
        return []

    # Simple keyword relevance matching across chunks (supporting words and CJK n-grams)
    query_tokens = [t.lower() for t in query.split() if len(t) > 1]
    cjk_chars = [ch for ch in query if "\u4e00" <= ch <= "\u9fff" or ch.isalnum()]
    for i in range(len(cjk_chars) - 1):
        query_tokens.append("".join(cjk_chars[i:i + 2]).lower())
    if not query_tokens:
        query_tokens = [query.lower()]
    matched_chunks: list[dict[str, Any]] = []

    for chunk in chunks:
        content = str(chunk.get("content", "")).lower()
        title = str(chunk.get("title", "")).lower()
        score = sum(1 for tok in query_tokens if tok in content or tok in title)
        if score > 0:
            matched_chunks.append({
                "chunk_id": chunk.get("chunk_id"),
                "title": chunk.get("title"),
                "source_id": chunk.get("source_id") or chunk.get("source_path"),
                "source_path": chunk.get("source_path"),
                "content": chunk.get("content"),
                "score": float(score),
            })

    matched_chunks.sort(key=lambda c: c["score"], reverse=True)
    top_k = manifest.retriever_config.get("top_k", 5)
    return matched_chunks[:top_k]

from .agent_behavior_scorer import AgentBehaviorScorer
from .errors import (
    EvaluationNotFoundError,
    EvaluationValidationError,
    EvaluationVersionConflictError,
)
from .models import EvaluationAuditEvent, EvaluationCriteria
from .real_rag_adapters import RealRagAnswerAdapter, RealRagRetrieverAdapter
from .repository import EvaluationRepository
from .runner_models import (
    CaseExecution,
    EvaluationRun,
    MetricResult,
    RunComparisonSummary,
    TargetExecutionInput,
    TargetSide,
)
from .scorer import EvaluationScorer
from .tool_fixture_models import ToolCallTrace, TrajectoryTrace, TurnExecutionTrace
from .tool_fixtures import ToolFixtureService

logger = logging.getLogger(__name__)

RetrieverFn = Callable[..., list[dict[str, Any]]]
ModelAnsweringFn = Callable[..., Any]
_CAS_MAX_ATTEMPTS = 3


class EvaluationRunner:
    """Orchestrates dual-side evaluation runs, budget controls, and comparison summaries."""

    def __init__(
        self,
        repository: EvaluationRepository,
        scorer: EvaluationScorer | None = None,
        agent_scorer: AgentBehaviorScorer | None = None,
        tool_fixture_service: ToolFixtureService | None = None,
        retriever_fn: Any | None = None,
        answering_fn: Any | None = None,
        releases_dir: Path | None = None,
        strict_real_rag: bool = False,
        chat_model: Any | None = None,
        model_invoker: Any | None = None,
        model_factory: Any | None = None,
        prompt_resolver: Any | None = None,
        lease_guard: Callable[[], None] | None = None,
        sandbox_adapter: Any | None = None,
        checkpoint_saver: Callable[[str], None] | None = None,
    ) -> None:
        self._repo = repository
        self._scorer = scorer or EvaluationScorer()
        self._agent_scorer = agent_scorer or AgentBehaviorScorer()
        self._tool_fixture_service = tool_fixture_service or ToolFixtureService()
        self._releases_dir = releases_dir
        self._strict_real_rag = strict_real_rag
        self._lease_guard = lease_guard
        self._checkpoint_saver = checkpoint_saver
        self._sandbox_adapter = sandbox_adapter

        self._retriever_fn = retriever_fn
        self._answering_fn = answering_fn
        # Auto-wire formal REAL_RAG adapters when releases_dir is provided
        if self._retriever_fn is None and releases_dir is not None:
            self._retriever_fn = RealRagRetrieverAdapter(releases_dir=releases_dir)
        if self._answering_fn is None and releases_dir is not None:
            self._answering_fn = RealRagAnswerAdapter(
                chat_model=chat_model,
                model_invoker=model_invoker,
                model_factory=model_factory,
                prompt_resolver=prompt_resolver,
                allow_synthetic_fallback=not strict_real_rag,
            )

    def has_retriever_adapter(self) -> bool:
        return self._retriever_fn is not None

    def has_answering_adapter(self) -> bool:
        if self._answering_fn is None:
            return False
        if self._strict_real_rag and hasattr(self._answering_fn, "is_real_model_configured"):
            return bool(self._answering_fn.is_real_model_configured())
        return True

    def has_sandbox_adapter(self) -> bool:
        if self._sandbox_adapter is not None:
            if hasattr(self._sandbox_adapter, "is_real_workflow_configured"):
                return bool(self._sandbox_adapter.is_real_workflow_configured())
            return True
        return False

    def execute_run(self, run_id: str) -> EvaluationRun:
        """Executes an evaluation run synchronously or from a background worker."""
        state = self._repo.load()
        run = next((r for r in state.runs if r.run_id == run_id), None)
        if not run:
            raise EvaluationNotFoundError(f"Evaluation run not found: {run_id}")

        if run.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            return run

        set_version = self._repo.get_set_version(run.set_version_id)
        if not set_version:
            raise EvaluationNotFoundError(
                f"EvalSetVersion {run.set_version_id} not found"
            )

        if run.mode == "REAL_RAG":
            if not self.has_retriever_adapter() or not self.has_answering_adapter():
                raise EvaluationValidationError(
                    "REAL_RAG execution rejected: Missing registered real retriever and answer adapters. "
                    "Ephemeral mock or keyword fallback is prohibited for production evaluation."
                )
        if run.mode == "AGENT_SANDBOX":
            if not self.has_sandbox_adapter():
                raise EvaluationValidationError(
                    "AGENT_SANDBOX execution rejected: Missing registered formal Agent workflow adapter. "
                    "Tool fixtures alone are not sufficient for production sandbox evaluation."
                )

        now = datetime.now(timezone.utc)
        # Update run status to RUNNING
        updated_run = run.model_copy(
            update={"status": "RUNNING", "started_at": now}
        )
        self._save_run_state(updated_run)

        # Resolve revisions
        revision_map = {r.revision_id: r for r in state.revisions}
        case_revisions: list[CaseRevision] = []
        for r_id in set_version.case_revision_ids:
            if r_id in revision_map:
                case_revisions.append(revision_map[r_id])

        limits = run.limits or {}
        max_cases = limits.get("max_cases")
        if max_cases:
            case_revisions = case_revisions[:max_cases]

        max_tokens = limits.get("max_tokens", float("inf"))
        max_cost_usd = limits.get("max_cost_usd", float("inf"))

        executed_cases: list[CaseExecution] = []
        total_tokens = 0
        total_cost = 0.0
        cancel_reason = None

        # Resume from per-case/side checkpoints when present.
        prior_state = self._repo.load()
        completed_sides = {
            (e.case_id, e.target_side): e
            for e in prior_state.case_executions
            if e.run_id == run_id and e.status in {"COMPLETED", "FAILED"}
        }

        # Execute both sides for each case
        for revision in case_revisions:
            # Check for cancellation between cases
            fresh_run = self._repo.get_run(run_id)
            if fresh_run and fresh_run.status in {"CANCELLING", "CANCELLED"}:
                cancel_reason = fresh_run.cancel_reason or "User cancelled run"
                break

            # Check budget limits
            if total_tokens >= max_tokens or total_cost >= max_cost_usd:
                cancel_reason = "Budget limit reached: max_cost_usd or max_tokens exceeded"
                break

            # 1. BASELINE SIDE
            baseline_key = (revision.case_id, "BASELINE")
            if baseline_key in completed_sides:
                b_exec = completed_sides[baseline_key]
            else:
                b_exec = self._execute_side(
                    run_id=run.run_id,
                    case_revision=revision,
                    manifest=run.baseline_manifest,
                    side="BASELINE",
                    mode=run.mode,
                )
                self._persist_case_execution(b_exec)
                self._save_progress_checkpoint(
                    f"{run.run_id}:{revision.case_id}:BASELINE:{b_exec.status}"
                )
            executed_cases.append(b_exec)
            total_tokens += b_exec.used_tokens
            total_cost += b_exec.estimated_cost_usd

            # 2. CANDIDATE SIDE
            candidate_key = (revision.case_id, "CANDIDATE")
            if candidate_key in completed_sides:
                c_exec = completed_sides[candidate_key]
            else:
                c_exec = self._execute_side(
                    run_id=run.run_id,
                    case_revision=revision,
                    manifest=run.candidate_manifest,
                    side="CANDIDATE",
                    mode=run.mode,
                )
                self._persist_case_execution(c_exec)
                self._save_progress_checkpoint(
                    f"{run.run_id}:{revision.case_id}:CANDIDATE:{c_exec.status}"
                )
            executed_cases.append(c_exec)
            total_tokens += c_exec.used_tokens
            total_cost += c_exec.estimated_cost_usd

        # Compute comparison summary
        summary = self._compute_comparison_summary(
            total_cases=len(case_revisions),
            executed_cases=executed_cases,
            total_cost=total_cost,
        )

        completed_at = datetime.now(timezone.utc)
        final_status = "CANCELLED" if cancel_reason else "COMPLETED"
        has_unknown_tokens = any(e.usage_status == "UNKNOWN" for e in executed_cases)
        cost_status = "PARTIAL_UNKNOWN" if has_unknown_tokens else "EXACT"
        is_eval_eligible = (run.mode != "OFFLINE_BENCHMARK")

        final_run = run.model_copy(
            update={
                "status": final_status,
                "completed_at": completed_at,
                "summary": summary,
                "cancel_reason": cancel_reason,
                "actual_cost_usd": round(total_cost, 4),
                "actual_tokens": total_tokens,
                "cost_status": cost_status,
                "is_eval_eligible": is_eval_eligible,
            }
        )

        # Commit mutation atomically with CAS
        last_conflict: EvaluationVersionConflictError | None = None
        for attempt in range(_CAS_MAX_ATTEMPTS):
            self._check_lease()
            current_state = self._repo.load()
            runs = [r for r in current_state.runs if r.run_id != run_id]
            runs.append(final_run)
            # Preserve executions from concurrent writers for other runs; replace this run's.
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
                self._repo.commit_mutation(
                    new_state, audit=audit, expected_revision=current_state.revision
                )
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

    def _execute_side(
        self,
        run_id: str,
        case_revision: CaseRevision,
        manifest: TargetManifest,
        side: TargetSide,
        mode: str = "REAL_RAG",
    ) -> CaseExecution:
        """Executes a single side (baseline or candidate) for a case revision."""
        execution_id = f"exec_{run_id[:8]}_{side.lower()}_{case_revision.case_id[:8]}"
        start_time = time.perf_counter()

        if case_revision.turns:
            return self._execute_multi_turn(
                run_id,
                case_revision,
                manifest,
                side,
                start_time,
                mode=mode,
            )

        # F01-T3: Strictly sanitize input to target under test - never pass golden answers or criteria
        sanitized_input = TargetExecutionInput(
            query=case_revision.query,
            conversation_history=(),
            persona_context=manifest.retriever_config.get("persona_context", {}) if manifest.persona_fixture_id else {},
            actor_id=manifest.target_id,
            tenant_id="default",
            owner_unit_id="default",
            environment=manifest.environment,
            case_id=case_revision.case_id,
        )

        try:
            # 1. Retrieval phase
            if self._retriever_fn:
                try:
                    retrieved = self._retriever_fn(case_revision.query, manifest, sanitized_input)
                except TypeError:
                    retrieved = self._retriever_fn(case_revision.query, manifest, case_revision)
            else:
                retrieved = default_knowledge_retriever(
                    case_revision.query, manifest, case_revision, self._releases_dir
                )

            # 2. Answering / sandbox workflow phase
            tool_calls: list[ToolCallTrace] = []
            provider_req_id = None
            sandbox_trace: dict[str, Any] | None = None
            if mode == "AGENT_SANDBOX":
                if self._sandbox_adapter is None:
                    raise EvaluationValidationError(
                        "AGENT_SANDBOX execution rejected: Missing registered formal Agent workflow adapter."
                    )
                workflow_result = self._sandbox_adapter.execute_workflow_turn(
                    case_revision.query, manifest, sanitized_input
                )
                if isinstance(workflow_result, dict):
                    sandbox_trace = dict(workflow_result)
                    answer = str(workflow_result.get("answer") or "").strip()
                    status = str(workflow_result.get("status") or "").upper()
                    if status in {"FAILED", "UNAVAILABLE"} or not answer:
                        raise EvaluationValidationError(
                            "AGENT_SANDBOX execution rejected: workflow did not return "
                            "a real answer from AgentWorkflow execution "
                            f"(status={status or 'missing'})."
                        )
                    tokens = workflow_result.get("tokens", 0)
                    cost = float(workflow_result.get("cost_usd") or 0.0)
                    raw_tool_calls = workflow_result.get("tool_calls") or []
                    tool_calls = list(raw_tool_calls)
                    provider_req_id = workflow_result.get("provider_request_id")
                    upstream_usage_status = workflow_result.get("usage_status")
                else:
                    raise EvaluationValidationError(
                        "AGENT_SANDBOX execution rejected: workflow executor must return "
                        "a structured result with answer and tool_calls."
                    )
            elif self._answering_fn:
                try:
                    ans_res = self._answering_fn(
                        case_revision.query, manifest, sanitized_input, retrieved
                    )
                except TypeError:
                    ans_res = self._answering_fn(
                        case_revision.query, manifest, case_revision, retrieved
                    )

                if isinstance(ans_res, tuple) and len(ans_res) >= 6:
                    answer, tokens, cost, raw_tool_calls, provider_req_id, upstream_usage_status = ans_res[:6]
                    tool_calls = list(raw_tool_calls)
                elif isinstance(ans_res, tuple) and len(ans_res) == 5:
                    answer, tokens, cost, raw_tool_calls, provider_req_id = ans_res
                    tool_calls = list(raw_tool_calls)
                    upstream_usage_status = None
                elif isinstance(ans_res, tuple) and len(ans_res) == 4:
                    answer, tokens, cost, raw_tool_calls = ans_res
                    tool_calls = list(raw_tool_calls)
                    upstream_usage_status = None
                else:
                    answer, tokens, cost = ans_res[:3]
                    upstream_usage_status = None
            else:
                # Default mock answer fallback
                answer = f"這是針對「{case_revision.query}」的依據回覆 [來源: {manifest.target_id}]"
                tokens = 150
                cost = 0.00005
                upstream_usage_status = None

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # Spec 6.2: Token usage handling (preserve upstream ESTIMATED / EXACT / UNKNOWN)
            if tokens is None or str(tokens).upper() == "UNKNOWN":
                actual_tokens = None
                used_tokens = 0
                usage_status = "UNKNOWN"
            else:
                actual_tokens = int(tokens)
                used_tokens = int(tokens)
                if upstream_usage_status and str(upstream_usage_status).upper() in {
                    "ESTIMATED",
                    "EXACT",
                    "UNKNOWN",
                }:
                    usage_status = str(upstream_usage_status).upper()
                else:
                    usage_status = "EXACT"

            evidence_ids = tuple(
                str(c.get("chunk_id") or c.get("evidence_id") or c.get("source_id"))
                for c in retrieved
                if (c.get("chunk_id") or c.get("evidence_id") or c.get("source_id"))
            )
            tool_events = tuple(
                c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)
                for c in tool_calls
            )

            # 3. Scoring phase
            metric_results, failure_class, passed = self._scorer.evaluate_execution(
                case_revision=case_revision,
                answer=answer,
                retrieved_evidence=tuple(retrieved),
            )

            # Tool constraints scoring
            tc = case_revision.tool_constraints
            if tc and (tc.required_tools or tc.forbidden_tools or tc.allowed_tools or tc.parameter_constraints or tc.tool_order or tc.allowed_paths or tool_calls):
                tool_metrics = self._agent_scorer.score_tool_constraints(tc, tuple(tool_calls))
                metric_results = metric_results + tuple(tool_metrics)
                for tm in tool_metrics:
                    if tm.applicability and tm.pass_status == "FAIL":
                        passed = False
                        if tm.metric_id == "tool.forbidden_tools":
                            failure_class = "SAFETY_VIOLATION"
                        elif failure_class is None:
                            failure_class = "ANSWER_INCORRECT"

            is_critical = (not passed) and (case_revision.criticality == "CRITICAL")

            trace_ref: dict[str, Any] = {}
            if tool_calls:
                trace_ref["tool_calls"] = list(tool_events)
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
                is_critical_failure=is_critical,
                used_tokens=used_tokens,
                actual_tokens=actual_tokens,
                usage_status=usage_status,
                latency_ms=duration_ms,
                estimated_cost_usd=cost,
                evidence_ids=evidence_ids,
                provider_request_id=provider_req_id,
                tool_events=tool_events,
            )

        except Exception as e:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            metric_results, failure_class, passed = self._scorer.evaluate_execution(
                case_revision=case_revision,
                answer="",
                retrieved_evidence=(),
                error_message=str(e),
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
                error_detail=str(e),
            )

    def _execute_multi_turn(
        self,
        run_id: str,
        case_revision: CaseRevision,
        manifest: TargetManifest,
        side: TargetSide,
        start_time: float,
        *,
        mode: str = "REAL_RAG",
    ) -> CaseExecution:
        """Executes a multi-turn scenario where agent answers form conversational history."""
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
                user_query = turn.user_query

                # F01-T3: Sanitize turn input
                turn_input = TargetExecutionInput(
                    query=user_query,
                    conversation_history=tuple(conversation_history),
                    persona_context=manifest.retriever_config.get("persona_context", {}) if manifest.persona_fixture_id else {},
                    actor_id=manifest.target_id,
                    tenant_id="default",
                    owner_unit_id="default",
                    environment=manifest.environment,
                    case_id=case_revision.case_id,
                )

                if self._retriever_fn:
                    try:
                        retrieved = self._retriever_fn(user_query, manifest, turn_input)
                    except TypeError:
                        retrieved = self._retriever_fn(user_query, manifest, case_revision)
                else:
                    retrieved = default_knowledge_retriever(
                        user_query, manifest, case_revision, self._releases_dir
                    )
                all_retrieved.extend(retrieved)

                tool_calls: list[ToolCallTrace] = []
                turn_usage: str | None = None
                if mode == "AGENT_SANDBOX":
                    if self._sandbox_adapter is None:
                        raise EvaluationValidationError(
                            "AGENT_SANDBOX execution rejected: Missing registered "
                            "formal Agent workflow adapter."
                        )
                    workflow_result = self._sandbox_adapter.execute_workflow_turn(
                        user_query, manifest, turn_input
                    )
                    if not isinstance(workflow_result, dict):
                        raise EvaluationValidationError(
                            "AGENT_SANDBOX execution rejected: workflow executor must "
                            "return a structured result with answer and tool_calls."
                        )
                    answer = str(workflow_result.get("answer") or "").strip()
                    status = str(workflow_result.get("status") or "").upper()
                    if status in {"FAILED", "UNAVAILABLE"} or not answer:
                        raise EvaluationValidationError(
                            "AGENT_SANDBOX multi-turn rejected: workflow did not return "
                            f"a real answer (status={status or 'missing'}, turn={idx})."
                        )
                    tokens = workflow_result.get("tokens", 0)
                    cost = float(workflow_result.get("cost_usd") or 0.0)
                    tool_calls = list(workflow_result.get("tool_calls") or [])
                    turn_usage = workflow_result.get("usage_status")
                elif self._answering_fn:
                    try:
                        ans_res = self._answering_fn(
                            user_query, manifest, turn_input, retrieved, conversation_history
                        )
                    except TypeError:
                        try:
                            ans_res = self._answering_fn(
                                user_query, manifest, turn_input, retrieved
                            )
                        except TypeError:
                            ans_res = self._answering_fn(
                                user_query, manifest, case_revision, retrieved
                            )

                    if isinstance(ans_res, tuple) and len(ans_res) >= 6:
                        answer, tokens, cost, raw_tool_calls, _, turn_usage = ans_res[:6]
                        tool_calls = list(raw_tool_calls)
                    elif isinstance(ans_res, tuple) and len(ans_res) == 5:
                        answer, tokens, cost, raw_tool_calls, _ = ans_res
                        tool_calls = list(raw_tool_calls)
                    elif isinstance(ans_res, tuple) and len(ans_res) == 4:
                        answer, tokens, cost, raw_tool_calls = ans_res
                        tool_calls = list(raw_tool_calls)
                    else:
                        answer, tokens, cost = ans_res[:3]
                else:
                    answer = f"Turn {idx + 1} response to '{user_query}'"
                    tokens = 120
                    cost = 0.00004

                all_tool_calls.extend(tool_calls)
                if tokens is not None:
                    total_tokens += tokens
                total_cost += cost

                if tokens is None or str(tokens).upper() == "UNKNOWN":
                    turn_usage_statuses.append("UNKNOWN")
                else:
                    turn_usage_statuses.append(str(turn_usage).upper() if turn_usage else "EXACT")

                # Mandatory GE3 rule: Expected answer is NEVER used as assistant history.
                # Actual model answer is used.
                conversation_history.append({"role": "user", "content": user_query})
                conversation_history.append({"role": "assistant", "content": answer})

                turn_metrics: list[MetricResult] = []
                turn_rev = case_revision.model_copy(
                    update={
                        "query": user_query,
                        "criteria": turn.criteria or EvaluationCriteria(),
                        "evidence": turn.evidence,
                        "behavior": turn.expected_behavior,
                    }
                )
                t_metrics, _, _ = self._scorer.evaluate_execution(
                    case_revision=turn_rev,
                    answer=answer,
                    retrieved_evidence=tuple(retrieved),
                )
                turn_metrics.extend(t_metrics)

                turn_passed = all(
                    m.pass_status == "PASS" for m in turn_metrics if m.applicability
                )
                turn_traces.append(
                    TurnExecutionTrace(
                        turn_index=idx,
                        turn_id=turn.turn_id,
                        user_query=user_query,
                        agent_response=answer,
                        tool_calls=tuple(tool_calls),
                        metrics=tuple(turn_metrics),
                        passed=turn_passed,
                    )
                )

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            trajectory_metrics, failed_idx, failed_reason, traj_passed = (
                self._agent_scorer.score_trajectory_timeline(
                    case_revision=case_revision,
                    turns=tuple(turn_traces),
                )
            )

            final_answer = turn_traces[-1].agent_response if turn_traces else ""
            case_metrics: list[MetricResult] = []
            failure_class = None
            combined_answers = " \n".join(t.agent_response for t in turn_traces)
            if case_revision.criteria.forbidden_claims:
                fc_metric = self._scorer.score_forbidden_claims(case_revision, combined_answers)
                case_metrics.append(fc_metric)
                if fc_metric.pass_status == "FAIL":
                    failure_class = "SAFETY_VIOLATION"
            if case_revision.criteria.required_facts:
                rf_metric = self._scorer.score_required_facts(case_revision, combined_answers)
                case_metrics.append(rf_metric)
                if rf_metric.pass_status == "FAIL" and failure_class is None:
                    failure_class = "ANSWER_INCORRECT"

            all_combined_metrics = list(case_metrics) + list(trajectory_metrics)
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

            is_critical = (not overall_passed) and (case_revision.criticality == "CRITICAL")

            evidence_ids = tuple(
                str(c.get("chunk_id") or c.get("evidence_id") or c.get("source_id"))
                for c in all_retrieved
                if (c.get("chunk_id") or c.get("evidence_id") or c.get("source_id"))
            )
            tool_events = tuple(
                c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)
                for c in all_tool_calls
            )

            if any(s == "UNKNOWN" for s in turn_usage_statuses):
                multi_turn_usage = "UNKNOWN"
            elif any(s == "ESTIMATED" for s in turn_usage_statuses):
                multi_turn_usage = "ESTIMATED"
            else:
                multi_turn_usage = "EXACT"

            return CaseExecution(
                execution_id=execution_id,
                run_id=run_id,
                case_revision_id=case_revision.revision_id,
                case_id=case_revision.case_id,
                target_side=side,
                attempt=1,
                status="COMPLETED",
                answer=final_answer,
                retrieved_evidence=tuple(all_retrieved),
                trace_ref={
                    "trajectory": trajectory.model_dump(mode="json"),
                    "conversation_history": conversation_history,
                },
                metric_results=tuple(all_combined_metrics),
                failure_classification=failure_class,
                passed=overall_passed,
                is_critical_failure=is_critical,
                used_tokens=total_tokens,
                actual_tokens=total_tokens,
                usage_status=multi_turn_usage,
                latency_ms=duration_ms,
                estimated_cost_usd=round(total_cost, 6),
                evidence_ids=evidence_ids,
                tool_events=tool_events,
            )

        except Exception as e:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            metric_results, failure_class, _ = self._scorer.evaluate_execution(
                case_revision=case_revision,
                answer="",
                retrieved_evidence=(),
                error_message=str(e),
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

    def _compute_comparison_summary(
        self,
        total_cases: int,
        executed_cases: list[CaseExecution],
        total_cost: float,
    ) -> RunComparisonSummary:
        """Computes differential metrics: regressions, fixes, pass rates, and coverage."""
        baseline_by_rev: dict[str, CaseExecution] = {}
        candidate_by_rev: dict[str, CaseExecution] = {}

        for exec_item in executed_cases:
            if exec_item.target_side == "BASELINE":
                baseline_by_rev[exec_item.case_revision_id] = exec_item
            else:
                candidate_by_rev[exec_item.case_revision_id] = exec_item

        regressions: list[str] = []
        fixes: list[str] = []
        critical_failures: list[str] = []
        inconclusive: list[str] = []
        candidate_passed = 0
        baseline_passed = 0
        judged = 0

        common_rev_ids = set(baseline_by_rev.keys()) & set(candidate_by_rev.keys())

        for rev_id in common_rev_ids:
            b = baseline_by_rev[rev_id]
            c = candidate_by_rev[rev_id]

            if b.status != "COMPLETED" or c.status != "COMPLETED":
                inconclusive.append(rev_id)
                continue

            judged += 1
            if b.passed:
                baseline_passed += 1
            if c.passed:
                candidate_passed += 1

            if b.passed and not c.passed:
                regressions.append(rev_id)
            elif not b.passed and c.passed:
                fixes.append(rev_id)

            if c.is_critical_failure:
                critical_failures.append(rev_id)

        executed_count = len(common_rev_ids)
        coverage = round(judged / total_cases, 3) if total_cases > 0 else 0.0
        pass_rate = round(candidate_passed / judged, 3) if judged > 0 else None

        latencies = [e.latency_ms for e in executed_cases if e.latency_ms > 0]
        latencies.sort()
        p50 = latencies[len(latencies) // 2] if latencies else 0.0
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[min(p95_idx, len(latencies) - 1)] if latencies else 0.0

        return RunComparisonSummary(
            total_cases=total_cases,
            executed_cases=executed_count,
            judged_cases=judged,
            baseline_passed_cases=baseline_passed,
            candidate_passed_cases=candidate_passed,
            pass_rate=pass_rate,
            coverage=coverage,
            regressions=tuple(regressions),
            fixes=tuple(fixes),
            critical_failures=tuple(critical_failures),
            inconclusive_cases=tuple(inconclusive),
            actual_cost_usd=round(total_cost, 4),
            latency_p50_ms=round(p50, 2),
            latency_p95_ms=round(p95, 2),
        )

    def _check_lease(self) -> None:
        """Fail closed when an attached job lease guard reports lease loss."""
        if self._lease_guard is not None:
            self._lease_guard()

    def bind_lease_guard(self, lease_guard: Callable[[], None] | None) -> None:
        """Attach or clear a lease guard for the current job execution."""
        self._lease_guard = lease_guard

    def bind_checkpoint_saver(self, checkpoint_saver: Callable[[str], None] | None) -> None:
        """Attach or clear a per-progress checkpoint saver for resume."""
        self._checkpoint_saver = checkpoint_saver

    def _save_progress_checkpoint(self, checkpoint_ref: str) -> None:
        self._check_lease()
        if self._checkpoint_saver is not None:
            self._checkpoint_saver(checkpoint_ref)

    def _persist_case_execution(self, execution: CaseExecution) -> None:
        """Persist one case/side result immediately so resume can skip completed work."""
        last_conflict: EvaluationVersionConflictError | None = None
        for attempt in range(_CAS_MAX_ATTEMPTS):
            self._check_lease()
            state = self._repo.load()
            retained = [
                item
                for item in state.case_executions
                if not (
                    item.run_id == execution.run_id
                    and item.case_id == execution.case_id
                    and item.target_side == execution.target_side
                )
            ]
            try:
                self._repo.commit_mutation(
                    state.model_copy(
                        update={"case_executions": tuple(retained + [execution])}
                    ),
                    expected_revision=state.revision,
                )
                return
            except EvaluationVersionConflictError as exc:
                last_conflict = exc
                logger.warning(
                    "CAS conflict persisting execution %s (attempt %s/%s)",
                    execution.execution_id,
                    attempt + 1,
                    _CAS_MAX_ATTEMPTS,
                )
        assert last_conflict is not None
        raise last_conflict

    def _save_run_state(self, run: EvaluationRun) -> None:
        """Update run state with CAS retries to avoid lost concurrent updates."""
        last_conflict: EvaluationVersionConflictError | None = None
        for attempt in range(_CAS_MAX_ATTEMPTS):
            self._check_lease()
            state = self._repo.load()
            runs = [r for r in state.runs if r.run_id != run.run_id]
            runs.append(run)
            try:
                self._repo.commit_mutation(
                    state.model_copy(update={"runs": tuple(runs)}),
                    expected_revision=state.revision,
                )
                return
            except EvaluationVersionConflictError as exc:
                last_conflict = exc
                logger.warning(
                    "CAS conflict saving run %s (attempt %s/%s)",
                    run.run_id,
                    attempt + 1,
                    _CAS_MAX_ATTEMPTS,
                )
        assert last_conflict is not None
        raise last_conflict
