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

RetrievalCacheKey = tuple[str, frozenset[str], str, str, int, float, str, int, str, int, int]


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


def fuse_query_level_rrf(
    *result_sets: Sequence[SearchResult],
    query_weights: Sequence[float] | None = None,
    rrf_k: int = 60,
    previous: Sequence[SearchResult] | None = None,
    previous_weight: float | None = None,
) -> list[SearchResult]:
    """Fuse results across multi-query fanouts using reciprocal rank fusion.

    Preserves the ranking contract:
    - ``fusion_score`` stores the combined multi-query RRF score.
    - ``final_rank`` and ``fusion_rank`` follow the unified multi-query ordering.
    - ``score`` preserves the best individual evidence confidence.
    """
    valid_sets = [list(rs) for rs in result_sets if rs]
    if not valid_sets:
        return list(previous or [])
    if len(valid_sets) == 1 and not previous:
        return list(valid_sets[0])

    weights: list[float] = []
    if query_weights:
        weights = list(query_weights)
    for index in range(len(weights), len(valid_sets)):
        weights.append(1.0 if index == 0 else 0.7)

    scores: dict[str, float] = {}
    best_by_chunk: dict[str, SearchResult] = {}
    for prev_rank, prev_res in enumerate(previous or (), start=1):
        cid = prev_res.chunk.chunk_id
        best_by_chunk[cid] = prev_res
        if previous_weight:
            scores[cid] = scores.get(cid, 0.0) + (previous_weight / (rrf_k + prev_rank))

    for q_idx, rset in enumerate(valid_sets):
        w = weights[q_idx] if q_idx < len(weights) else 0.7
        for rank, result in enumerate(rset, start=1):
            cid = result.chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + (w / (rrf_k + rank))
            existing = best_by_chunk.get(cid)
            if existing is None or is_better_ranked(result, existing):
                best_by_chunk[cid] = result

    ordered_ids = sorted(
        best_by_chunk.keys(),
        key=lambda cid: (-scores.get(cid, 0.0), cid),
    )
    fused: list[SearchResult] = []
    for rank, cid in enumerate(ordered_ids, start=1):
        base = best_by_chunk[cid]
        combined_score = scores.get(cid, base.fusion_score or 0.0)
        fused.append(
            SearchResult(
                chunk=base.chunk,
                score=base.score,
                sparse_score=base.sparse_score,
                dense_score=base.dense_score,
                sparse_rank=base.sparse_rank,
                dense_rank=base.dense_rank,
                fusion_score=round(combined_score, 6),
                fusion_rank=rank,
                rerank_score=base.rerank_score,
                rerank_rank=base.rerank_rank,
                final_rank=rank,
            )
        )
    return fused


def merge_best_chunk_results(
    *result_sets: Sequence[SearchResult],
    previous: Sequence[SearchResult] | None = None,
) -> list[SearchResult]:
    """Dedupe by chunk id, keeping the better-ranked hit; preserve ranking order.

    Must not re-sort by evidence confidence (``score``), which would wash out
    RRF / reranker ordering after multi-query fusion.
    """
    valid_sets = [rs for rs in result_sets if rs]
    if len(valid_sets) > 1:
        return fuse_query_level_rrf(*valid_sets, previous=previous)
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
