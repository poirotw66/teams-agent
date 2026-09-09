from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import EvaluationNotFoundError
from .models import CaseRevision, EvaluationAuditEvent
from .repository import EvaluationRepository
from .runner_models import (
    CaseExecution,
    EvaluationRun,
    RunComparisonSummary,
    TargetManifest,
    TargetSide,
)
from .scorer import EvaluationScorer

logger = logging.getLogger(__name__)

RetrieverFn = Callable[[str, TargetManifest, CaseRevision], list[dict[str, Any]]]
ModelAnsweringFn = Callable[
    [str, TargetManifest, CaseRevision, list[dict[str, Any]]],
    tuple[str, int, float],  # (answer, tokens, cost_usd)
]


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


class EvaluationRunner:
    """Orchestrates dual-side evaluation runs, budget controls, and comparison summaries."""

    def __init__(
        self,
        repository: EvaluationRepository,
        scorer: EvaluationScorer | None = None,
        retriever_fn: RetrieverFn | None = None,
        answering_fn: ModelAnsweringFn | None = None,
        releases_dir: Path | None = None,
    ) -> None:
        self._repo = repository
        self._scorer = scorer or EvaluationScorer()
        self._retriever_fn = retriever_fn
        self._answering_fn = answering_fn
        self._releases_dir = releases_dir

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
            b_exec = self._execute_side(
                run_id=run.run_id,
                case_revision=revision,
                manifest=run.baseline_manifest,
                side="BASELINE",
            )
            executed_cases.append(b_exec)
            total_tokens += b_exec.used_tokens
            total_cost += b_exec.estimated_cost_usd

            # 2. CANDIDATE SIDE
            c_exec = self._execute_side(
                run_id=run.run_id,
                case_revision=revision,
                manifest=run.candidate_manifest,
                side="CANDIDATE",
            )
            executed_cases.append(c_exec)
            total_tokens += c_exec.used_tokens
            total_cost += c_exec.estimated_cost_usd

        # Save all executed cases
        current_state = self._repo.load()
        existing_executions = [e for e in current_state.case_executions if e.run_id != run_id]
        existing_executions.extend(executed_cases)

        # Compute comparison summary
        summary = self._compute_comparison_summary(
            total_cases=len(case_revisions),
            executed_cases=executed_cases,
            total_cost=total_cost,
        )

        completed_at = datetime.now(timezone.utc)
        final_status = "CANCELLED" if cancel_reason else "COMPLETED"

        final_run = run.model_copy(
            update={
                "status": final_status,
                "completed_at": completed_at,
                "summary": summary,
                "cancel_reason": cancel_reason,
                "actual_cost_usd": round(total_cost, 4),
                "actual_tokens": total_tokens,
            }
        )

        # Commit mutation atomically
        runs = [r for r in current_state.runs if r.run_id != run_id]
        runs.append(final_run)
        new_state = current_state.model_copy(
            update={
                "runs": tuple(runs),
                "case_executions": tuple(existing_executions),
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
        self._repo.commit_mutation(new_state, audit=audit)
        return final_run

    def _execute_side(
        self,
        run_id: str,
        case_revision: CaseRevision,
        manifest: TargetManifest,
        side: TargetSide,
    ) -> CaseExecution:
        """Executes a single side (baseline or candidate) for a case revision."""
        execution_id = f"exec_{run_id[:8]}_{side.lower()}_{case_revision.case_id[:8]}"
        start_time = time.perf_counter()

        try:
            # 1. Retrieval phase
            if self._retriever_fn:
                retrieved = self._retriever_fn(case_revision.query, manifest, case_revision)
            else:
                retrieved = default_knowledge_retriever(
                    case_revision.query, manifest, case_revision, self._releases_dir
                )

            # 2. Answering phase
            if self._answering_fn:
                answer, tokens, cost = self._answering_fn(
                    case_revision.query, manifest, case_revision, retrieved
                )
            else:
                # Default mock answer fallback
                answer = f"這是針對「{case_revision.query}」的依據回覆 [來源: {manifest.target_id}]"
                tokens = 150
                cost = 0.00005

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # 3. Scoring phase
            metric_results, failure_class, passed = self._scorer.evaluate_execution(
                case_revision=case_revision,
                answer=answer,
                retrieved_evidence=tuple(retrieved),
            )

            is_critical = (not passed) and (case_revision.criticality == "CRITICAL")

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
                metric_results=metric_results,
                failure_classification=failure_class,
                passed=passed,
                is_critical_failure=is_critical,
                used_tokens=tokens,
                latency_ms=duration_ms,
                estimated_cost_usd=cost,
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

    def _save_run_state(self, run: EvaluationRun) -> None:
        """Helper to update run state in repository."""
        state = self._repo.load()
        runs = [r for r in state.runs if r.run_id != run.run_id]
        runs.append(run)
        self._repo.commit_mutation(state.model_copy(update={"runs": tuple(runs)}))
