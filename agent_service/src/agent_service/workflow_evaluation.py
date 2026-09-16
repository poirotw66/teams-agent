"""Metrics for end-to-end workflow routing evaluations."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowEvaluationRecord:
    """Expected and observed outcomes for one evaluation case."""

    expected_queries: tuple[str, ...]
    observed_queries: tuple[str, ...]
    supervisor_terminated: bool
    observed_issue_count: int
    clarification_count: int
    max_expected_clarification_turns: int
    expects_grounded_answer: bool
    has_grounded_answer: bool
    llm_call_count: int
    latency_ms: float


@dataclass(frozen=True)
class WorkflowEvaluationSummary:
    """Aggregate accuracy, cost, and latency signals for one evaluation run."""

    case_count: int
    it_block_rate: float
    issue_split_accuracy: float
    unnecessary_clarification_rate: float
    retrieval_query_accuracy: float
    grounded_answer_rate: float
    mean_llm_call_count: float
    p95_latency_ms: float


def summarize_workflow_evaluation(
    records: list[WorkflowEvaluationRecord],
) -> WorkflowEvaluationSummary:
    """Aggregate exact-match workflow metrics without hiding missing cases."""
    if not records:
        raise ValueError("At least one workflow evaluation record is required.")

    grounded_records = [record for record in records if record.expects_grounded_answer]
    latencies = sorted(record.latency_ms for record in records)
    return WorkflowEvaluationSummary(
        case_count=len(records),
        it_block_rate=_rate(record.supervisor_terminated for record in records),
        issue_split_accuracy=_rate(
            record.observed_issue_count == len(record.expected_queries)
            for record in records
        ),
        unnecessary_clarification_rate=_rate(
            record.clarification_count > record.max_expected_clarification_turns
            for record in records
        ),
        retrieval_query_accuracy=_rate(
            record.observed_queries == record.expected_queries for record in records
        ),
        grounded_answer_rate=(
            _rate(record.has_grounded_answer for record in grounded_records)
            if grounded_records
            else 1.0
        ),
        mean_llm_call_count=(
            sum(record.llm_call_count for record in records) / len(records)
        ),
        p95_latency_ms=latencies[math.ceil(len(latencies) * 0.95) - 1],
    )


def _rate(outcomes: Iterable[bool]) -> float:
    resolved = tuple(outcomes)
    return sum(resolved) / len(resolved)
