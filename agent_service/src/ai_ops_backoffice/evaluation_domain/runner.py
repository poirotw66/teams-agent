"""Evaluation run orchestration: dual-side execution, budgets, and comparison."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_behavior_scorer import AgentBehaviorScorer
from .errors import (
    EvaluationNotFoundError,
    EvaluationValidationError,
    EvaluationVersionConflictError,
)
from .models import CaseRevision
from .real_rag_adapters import RealRagAnswerAdapter, RealRagRetrieverAdapter
from .repository import EvaluationRepository
from .runner_execute import (
    build_final_run,
    commit_run_completion,
    execute_case_loop,
    resolve_case_revisions,
)
from .runner_models import (
    CaseExecution,
    EvaluationRun,
    RunComparisonSummary,
    TargetManifest,
    TargetSide,
)
from .runner_side_execution import CaseSideExecutor, default_knowledge_retriever
from .scorer import EvaluationScorer
from .tool_fixtures import ToolFixtureService

logger = logging.getLogger(__name__)

RetrieverFn = Callable[..., list[dict[str, Any]]]
ModelAnsweringFn = Callable[..., Any]
_CAS_MAX_ATTEMPTS = 3

__all__ = [
    "EvaluationRunner",
    "default_knowledge_retriever",
]


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
        self._side_executor = CaseSideExecutor(
            scorer=self._scorer,
            agent_scorer=self._agent_scorer,
            retriever_fn=self._retriever_fn,
            answering_fn=self._answering_fn,
            sandbox_adapter=self._sandbox_adapter,
            releases_dir=self._releases_dir,
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
            raise EvaluationNotFoundError(f"EvalSetVersion {run.set_version_id} not found")

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
        updated_run = run.model_copy(update={"status": "RUNNING", "started_at": now})
        self._save_run_state(updated_run)

        limits = run.limits or {}
        case_revisions = resolve_case_revisions(
            state=state,
            set_version=set_version,
            max_cases=limits.get("max_cases"),
        )
        prior_state = self._repo.load()
        completed_sides = {
            (e.case_id, e.target_side): e
            for e in prior_state.case_executions
            if e.run_id == run_id and e.status in {"COMPLETED", "FAILED"}
        }
        executed_cases, total_tokens, total_cost, cancel_reason = execute_case_loop(
            run=run,
            run_id=run_id,
            case_revisions=case_revisions,
            completed_sides=completed_sides,
            max_tokens=limits.get("max_tokens", float("inf")),
            max_cost_usd=limits.get("max_cost_usd", float("inf")),
            repo=self._repo,
            execute_or_resume_side=self._execute_or_resume_side,
        )
        final_run = build_final_run(
            run=run,
            executed_cases=executed_cases,
            total_tokens=total_tokens,
            total_cost=total_cost,
            cancel_reason=cancel_reason,
            case_revision_count=len(case_revisions),
            compute_comparison_summary=self._compute_comparison_summary,
        )
        return commit_run_completion(
            repo=self._repo,
            run=run,
            run_id=run_id,
            final_run=final_run,
            executed_cases=executed_cases,
            total_cost=total_cost,
            cancel_reason=cancel_reason,
            check_lease=self._check_lease,
        )

    def _execute_or_resume_side(
        self,
        *,
        run: EvaluationRun,
        revision: CaseRevision,
        side: TargetSide,
        manifest: TargetManifest,
        completed_sides: dict[tuple[str, str], CaseExecution],
    ) -> CaseExecution:
        key = (revision.case_id, side)
        if key in completed_sides:
            return completed_sides[key]
        execution = self._execute_side(
            run_id=run.run_id,
            case_revision=revision,
            manifest=manifest,
            side=side,
            mode=run.mode,
        )
        self._persist_case_execution(execution)
        self._save_progress_checkpoint(f"{run.run_id}:{revision.case_id}:{side}:{execution.status}")
        return execution

    def _execute_side(
        self,
        run_id: str,
        case_revision: CaseRevision,
        manifest: TargetManifest,
        side: TargetSide,
        mode: str = "REAL_RAG",
    ) -> CaseExecution:
        """Facade for case-side execution (kept for tests and callers)."""
        return self._side_executor.execute_side(run_id, case_revision, manifest, side, mode=mode)

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
        """Facade for multi-turn execution (kept for tests and callers)."""
        return self._side_executor.execute_multi_turn(
            run_id,
            case_revision,
            manifest,
            side,
            start_time,
            mode=mode,
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
                    state.model_copy(update={"case_executions": tuple(retained + [execution])}),
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
