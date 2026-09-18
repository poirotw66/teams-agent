"""Retrieval cache key, query fan-out, and result-merge helpers.

Index I/O and cache mutation stay on ``HybridKnowledgeService``; this module
owns the pure query/result bookkeeping used around ``HybridIndex.search``.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_service.retrieval import SearchResult

RETRIEVAL_CANDIDATE_MULTIPLIER = 3
MAX_RETRIEVAL_CACHE_SIZE = 500

RetrievalCacheKey = tuple[str, frozenset[str], str, str, int, float]


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
) -> RetrievalCacheKey:
    return (
        query.strip().casefold(),
        groups,
        environment,
        release_id,
        top_k,
        min_score,
    )


def merge_best_chunk_results(
    *result_sets: Sequence[SearchResult],
    previous: Sequence[SearchResult] | None = None,
) -> list[SearchResult]:
    best_by_chunk: dict[str, SearchResult] = {}
    for prev_res in previous or ():
        best_by_chunk[prev_res.chunk.chunk_id] = prev_res
    for result in (item for result_set in result_sets for item in result_set):
        current = best_by_chunk.get(result.chunk.chunk_id)
        if current is None or result.score > current.score:
            best_by_chunk[result.chunk.chunk_id] = result
    return sorted(
        best_by_chunk.values(),
        key=lambda item: item.score,
        reverse=True,
    )


def accumulate_stage_timings(
    stage_timings_ms: dict[str, float],
    timings: dict[str, float],
) -> None:
    for key, value in timings.items():
        # Sum of work across parallel facet searches; wall clock is retrievalMs.
        stage_timings_ms[key] = round(stage_timings_ms.get(key, 0.0) + value, 1)
