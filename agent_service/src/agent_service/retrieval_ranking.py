"""SearchResult ranking contract (RAG pipeline correctness).

``SearchResult.score`` is treated as *evidence confidence* for min_score /
relevance gates. Ordering must use ``ranking_sort_key`` / list ``final_rank``,
never re-sort by evidence confidence after RRF or rerank.
"""

from __future__ import annotations

from collections.abc import Sequence

from .retrieval import SearchResult

__all__ = [
    "evidence_confidence",
    "is_better_ranked",
    "ranking_sort_key",
    "sort_by_ranking",
]


def evidence_confidence(result: SearchResult) -> float:
    """Gate / confidence scale (legacy ``score`` field). Not a ranking key."""
    return float(result.score)


def ranking_sort_key(result: SearchResult) -> tuple[int, float, float, str]:
    """Ascending sort key for retrieval ranking (lower = better).

    Precedence:
    1. ``final_rank`` when set (canonical post-fusion / post-rerank position)
    2. Within the same rank tier, higher ``rerank_score`` / ``fusion_score``
    3. evidence confidence as last resort for pre-fusion lists
    """
    chunk_id = result.chunk.chunk_id
    if result.final_rank is not None:
        if result.rerank_score is not None:
            secondary = -float(result.rerank_score)
        elif result.fusion_score is not None:
            secondary = -float(result.fusion_score)
        else:
            secondary = -float(result.score)
        return (0, float(result.final_rank), secondary, chunk_id)
    if result.rerank_score is not None:
        return (1, -float(result.rerank_score), 0.0, chunk_id)
    if result.fusion_score is not None:
        return (2, -float(result.fusion_score), 0.0, chunk_id)
    return (3, -float(result.score), 0.0, chunk_id)


def is_better_ranked(candidate: SearchResult, incumbent: SearchResult) -> bool:
    """True when ``candidate`` should replace ``incumbent`` for the same chunk."""
    return ranking_sort_key(candidate) < ranking_sort_key(incumbent)


def sort_by_ranking(results: Sequence[SearchResult]) -> list[SearchResult]:
    """Stable reorder by ranking contract (does not mutate evidence scores)."""
    return sorted(results, key=ranking_sort_key)
