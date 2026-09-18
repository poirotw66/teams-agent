"""Deterministic post-retrieve query tiers for rewrite / retry budgets.

Trivial and standard queries stay on a single-pass RAG path. Only hard
queries keep retrieval rewrites and generation retries enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_service.retrieval import SearchResult

from .generator import query_asks_for_error_branching
from .grounding import (
    query_asks_for_procedure,
    query_asks_for_visual_evidence,
)
from .relevance import (
    _CLOSE_SCORE_GAP,
    conflicting_top_candidates,
    evaluate_retrieval_confidence,
    query_lexically_matches_results,
)
from .retrieval_state import RetrievalState


class QueryTier(StrEnum):
    TRIVIAL = "trivial"
    STANDARD = "standard"
    HARD = "hard"


@dataclass(frozen=True)
class QueryTierDecision:
    tier: QueryTier
    max_retrieval_rewrites: int
    enable_generation_retries: bool


def _has_close_top_gap(results: list[SearchResult]) -> bool:
    if len(results) < 2:
        return False
    return results[0].score - results[1].score < _CLOSE_SCORE_GAP


def _is_multi_aspect_query(state: RetrievalState) -> bool:
    query = state.resolved_issue_query
    if len(state.facet_queries) >= 2:
        return True
    return (
        query_asks_for_procedure(query)
        or query_asks_for_error_branching(query)
        or query_asks_for_visual_evidence(query)
    )


def classify_query_tier(
    state: RetrievalState,
    *,
    min_score: float,
    max_retrieval_rewrites: int,
) -> QueryTierDecision:
    """Classify after first retrieve; never adds an LLM call."""
    hard_ceiling = max(0, max_retrieval_rewrites)
    results = list(state.results)
    confidence_label, _ = evaluate_retrieval_confidence(
        query=state.resolved_issue_query,
        results=results,
        min_score=min_score,
        filter_displaced_top1=state.filter_displaced_top1,
    )
    multi_aspect = _is_multi_aspect_query(state)
    lexical = query_lexically_matches_results(state.resolved_issue_query, results)
    close_gap = _has_close_top_gap(results)
    conflicting = conflicting_top_candidates(results)

    if (
        confidence_label in {"BELOW_MIN_SCORE", "LOW_CONFIDENCE_FAIL"}
        or state.filter_displaced_top1
        or conflicting
        or (close_gap and not lexical)
        or multi_aspect
    ):
        return QueryTierDecision(
            tier=QueryTier.HARD,
            max_retrieval_rewrites=hard_ceiling,
            enable_generation_retries=True,
        )

    if (
        confidence_label == "HIGH_CONFIDENCE_PASS"
        and not close_gap
        and lexical
        and not multi_aspect
    ):
        return QueryTierDecision(
            tier=QueryTier.TRIVIAL,
            max_retrieval_rewrites=0,
            enable_generation_retries=False,
        )

    # Default bias: uncertain middle band stays standard (no rewrite/retry tax).
    return QueryTierDecision(
        tier=QueryTier.STANDARD,
        max_retrieval_rewrites=0,
        enable_generation_retries=False,
    )


__all__ = [
    "QueryTier",
    "QueryTierDecision",
    "classify_query_tier",
]
