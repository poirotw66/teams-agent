"""Retrieval cache key, query fan-out, and result-merge helpers.

Index I/O and cache mutation stay on ``HybridKnowledgeService``; this module
owns the pure query/result bookkeeping used around ``HybridIndex.search``.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_service.retrieval import SearchResult
from agent_service.retrieval_ranking import is_better_ranked, sort_by_ranking

RETRIEVAL_CANDIDATE_MULTIPLIER = 3
MAX_RETRIEVAL_CACHE_SIZE = 500

RetrievalCacheKey = tuple[
    str, frozenset[str], str, str, int, float, str, int, str, int, int
]


def resolve_retrieval_queries(
    search_query: str,
    facet_queries: Sequence[str],
    *,
    attempt: int,
) -> tuple[str, ...]:
    queries_to_run = [search_query]
    if attempt == 0 and facet_queries:
        queries_to_run.extend(facet_queries)
    return tuple(dict.fromkeys(query for query in queries_to_run if query.strip()))


def make_retrieval_cache_key(
    query: str,
    *,
    groups: frozenset[str],
    environment: str,
    release_id: str,
    top_k: int,
    min_score: float,
    fusion_mode: str = "RRF",
    rrf_k: int = 60,
    contextualization_version: str = "",
    candidate_limit: int = 20,
    fusion_candidate_k: int = 20,
) -> RetrievalCacheKey:
    return (
        query.strip().casefold(),
        groups,
        environment,
        release_id,
        top_k,
        min_score,
        fusion_mode.upper(),
        rrf_k,
        contextualization_version,
        candidate_limit,
        fusion_candidate_k,
    )


def merge_best_chunk_results(
    *result_sets: Sequence[SearchResult],
    previous: Sequence[SearchResult] | None = None,
) -> list[SearchResult]:
    """Dedupe by chunk id, keeping the better-ranked hit; preserve ranking order.

    Must not re-sort by evidence confidence (``score``), which would wash out
    RRF / reranker ordering after multi-query fusion.
    """
    best_by_chunk: dict[str, SearchResult] = {}
    for prev_res in previous or ():
        best_by_chunk[prev_res.chunk.chunk_id] = prev_res
    for result in (item for result_set in result_sets for item in result_set):
        current = best_by_chunk.get(result.chunk.chunk_id)
        if current is None or is_better_ranked(result, current):
            best_by_chunk[result.chunk.chunk_id] = result
    return sort_by_ranking(best_by_chunk.values())


def accumulate_stage_timings(
    stage_timings_ms: dict[str, float],
    timings: dict[str, float],
) -> None:
    for key, value in timings.items():
        # Sum of work across parallel facet searches; wall clock is retrievalMs.
        stage_timings_ms[key] = round(stage_timings_ms.get(key, 0.0) + value, 1)
