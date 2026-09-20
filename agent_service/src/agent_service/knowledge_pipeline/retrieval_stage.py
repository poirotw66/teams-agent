"""Retrieval stage orchestration extracted from HybridKnowledgeService."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from agent_service.rag_observability import (
    record_cache_hit,
    record_query_tier,
    rerank_span,
    retrieval_span,
)
from agent_service.reranker import Reranker, tier_meets_minimum
from agent_service.retrieval import SearchResult

from .query_tier import classify_query_tier
from .retrieval_state import RetrievalState
from .retriever import (
    MAX_RETRIEVAL_CACHE_SIZE,
    RETRIEVAL_CANDIDATE_MULTIPLIER,
    accumulate_stage_timings,
    fuse_query_level_rrf,
    make_retrieval_cache_key,
    resolve_retrieval_queries,
)
from .trace import build_retrieval_attempt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalHost:
    """Dependencies the retrieval stage needs from HybridKnowledgeService."""

    search_with_timings: Callable[..., tuple[list[SearchResult], dict[str, float]]]
    inject_enterprise_app_evidence: Callable[..., list[SearchResult]]
    select_document_chunks: Callable[[str, list[SearchResult]], tuple[list[SearchResult], bool]]
    top_k: int
    min_score: float
    deployment_environment: str
    release_id: str
    retrieval_cache: MutableMapping[tuple[Any, ...], list[SearchResult]]
    reranker: Reranker | None = None
    rerank_candidate_k: int = 24
    reranker_enabled: bool = False
    reranker_min_tier: str = "standard"
    reranker_model: str = "noop"
    fusion_mode: str = "RRF"
    fusion_candidate_k: int = 20
    rrf_k: int = 60
    contextualization_version: str = ""
    chunk_by_id: Mapping[str, Any] | None = None
    embed_queries: Callable[[Sequence[str]], Sequence[list[float]]] | None = None
    enable_batch_embedding: bool = True
    enable_query_rrf: bool = True


def retrieval_candidate_limit(host: RetrievalHost) -> int:
    """Pool size before rerank — never smaller than configured rerank/fusion k."""
    floors = [
        host.top_k * RETRIEVAL_CANDIDATE_MULTIPLIER,
        int(host.fusion_candidate_k or 0),
    ]
    if host.reranker_enabled:
        floors.append(int(host.rerank_candidate_k or 0))
    return max(floors)


async def _cached_search(
    host: RetrievalHost,
    query: str,
    *,
    groups: set[str],
    frozen_groups: frozenset[str],
    environment: str,
    query_vector: list[float] | None = None,
) -> tuple[list[SearchResult], dict[str, float]]:
    limit = retrieval_candidate_limit(host)
    cache_key = make_retrieval_cache_key(
        query,
        groups=frozen_groups,
        environment=environment,
        release_id=host.release_id,
        top_k=host.top_k,
        min_score=host.min_score,
        fusion_mode=host.fusion_mode,
        rrf_k=host.rrf_k,
        contextualization_version=host.contextualization_version,
        candidate_limit=limit,
        fusion_candidate_k=host.fusion_candidate_k,
    )
    cache = host.retrieval_cache
    if cache_key in cache:
        if isinstance(cache, OrderedDict):
            cache.move_to_end(cache_key)
        record_cache_hit(True)
        return cache[cache_key], {}
    record_cache_hit(False)
    search_kwargs: dict[str, Any] = {
        "environment": environment,
        "fusion_mode": host.fusion_mode,
    }
    if query_vector is not None:
        try:
            import inspect

            sig = inspect.signature(host.search_with_timings)
            if "query_vector" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            ):
                search_kwargs["query_vector"] = query_vector
        except Exception:
            pass

    with retrieval_span(
        fusion_mode=host.fusion_mode,
        release_id=host.release_id,
        cache_hit=False,
    ):
        res, timings = await asyncio.to_thread(
            host.search_with_timings,
            query,
            limit,
            groups,
            **search_kwargs,
        )
    cache[cache_key] = res
    if len(cache) > MAX_RETRIEVAL_CACHE_SIZE and isinstance(cache, OrderedDict):
        cache.popitem(last=False)
    elif len(cache) > MAX_RETRIEVAL_CACHE_SIZE:
        cache.pop(next(iter(cache)))
    return res, timings


async def _batch_embed_uncached_queries(
    host: RetrievalHost,
    retrieval_queries: Sequence[str],
    *,
    frozen_groups: frozenset[str],
    environment: str,
    limit: int,
) -> dict[str, list[float]]:
    """Embed uncached multi-query fanouts in a single batch when supported."""
    if not getattr(host, "enable_batch_embedding", True):
        return {}
    if not getattr(host, "embed_queries", None) or len(retrieval_queries) <= 1:
        return {}
    uncached = [
        q
        for q in retrieval_queries
        if make_retrieval_cache_key(
            q,
            groups=frozen_groups,
            environment=environment,
            release_id=host.release_id,
            top_k=host.top_k,
            min_score=host.min_score,
            fusion_mode=host.fusion_mode,
            rrf_k=host.rrf_k,
            contextualization_version=host.contextualization_version,
            candidate_limit=limit,
            fusion_candidate_k=host.fusion_candidate_k,
        )
        not in host.retrieval_cache
    ]
    if not uncached:
        return {}
    # Single-query leftovers should use the normal search embed path; a 1-item
    # "batch" only adds provider overhead without parallelism benefit.
    if len(uncached) <= 1:
        return {}
    query_vectors: dict[str, list[float]] = {}
    try:
        vectors = await asyncio.to_thread(host.embed_queries, uncached)
        for q, v in zip(uncached, vectors):
            if v:
                query_vectors[q] = v
    except Exception as exc:
        logger.debug("batch_query_embedding_fallback: %s", exc)
    return query_vectors


def _compute_query_weights(num_result_sets: int, attempt: int) -> list[float]:
    query_weights = [1.0]
    for idx in range(1, num_result_sets):
        query_weights.append(0.6 if attempt > 0 and idx == num_result_sets - 1 else 0.7)
    return query_weights


async def _maybe_rerank(
    host: RetrievalHost,
    *,
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    """Apply reranking when enabled, model is valid, and query meets min tier."""
    if not host.reranker or not host.reranker_enabled or not results:
        return results
    if host.reranker_model == "noop":
        return results
    provisional = classify_query_tier(
        RetrievalState(
            raw_user_utterance=query,
            resolved_issue_query=query,
            search_query=query,
            facet_queries=(),
            results=results,
        ),
        min_score=host.min_score,
        max_retrieval_rewrites=0,
    )
    record_query_tier(provisional.tier.value)
    if not tier_meets_minimum(provisional.tier.value, host.reranker_min_tier):
        return results
    limit = min(host.rerank_candidate_k, len(results))
    with rerank_span(
        reranker_model=host.reranker_model,
        candidate_count=limit,
        query_tier=provisional.tier.value,
    ):
        return await host.reranker.rerank(query=query, candidates=results, limit=limit)


async def _execute_multi_query_search(
    host: RetrievalHost,
    retrieval_queries: Sequence[str],
    groups: set[str],
    *,
    frozen_groups: frozenset[str],
    environment: str,
    limit: int,
    stage_timings_ms: dict[str, float],
) -> list[list[SearchResult]]:
    start_batch = time.perf_counter()
    query_vectors = await _batch_embed_uncached_queries(
        host,
        retrieval_queries,
        frozen_groups=frozen_groups,
        environment=environment,
        limit=limit,
    )
    if query_vectors:
        batch_ms = (time.perf_counter() - start_batch) * 1000.0
        stage_timings_ms["batchEmbeddingMs"] = round(batch_ms, 2)
        stage_timings_ms["batchEmbeddingQueryCount"] = float(len(query_vectors))
    search_outcomes = await asyncio.gather(
        *(
            _cached_search(
                host,
                query,
                groups=groups,
                frozen_groups=frozen_groups,
                environment=environment,
                query_vector=query_vectors.get(query),
            )
            for query in retrieval_queries
        )
    )
    for _results, timings in search_outcomes:
        accumulate_stage_timings(stage_timings_ms, timings)
    return [outcome[0] for outcome in search_outcomes]


def _append_trace_attempts(
    trace_attempts: list[Any],
    retrieval_queries: Sequence[str],
    result_sets: Sequence[list[SearchResult]],
    selected_chunk_ids: set[str],
) -> None:
    for retrieval_query, result_set in zip(retrieval_queries, result_sets, strict=True):
        trace_attempts.append(
            build_retrieval_attempt(
                retrieval_query,
                result_set,
                selected_chunk_ids,
            )
        )


def _merge_retrieval_result_sets(
    host: RetrievalHost,
    result_sets: Sequence[list[SearchResult]],
    *,
    attempt: int,
    previous_results: Sequence[SearchResult],
) -> list[SearchResult]:
    """Fuse multi-query / rewrite result sets under the ranking contract.

    Rewrite attempts often yield a single result_set (facets skipped). When a
    previous original ranking exists, fuse previous × 1.0 with rewrite × 0.6.
    """
    has_previous_ranking = bool(previous_results) and attempt > 0
    should_fuse_query_rrf = getattr(host, "enable_query_rrf", True) and (
        len(result_sets) > 1 or has_previous_ranking
    )
    if should_fuse_query_rrf:
        previous_weight = 1.0 if has_previous_ranking else None
        query_weights = (
            [0.6]
            if (has_previous_ranking and len(result_sets) == 1)
            else _compute_query_weights(len(result_sets), attempt)
        )
        return fuse_query_level_rrf(
            *result_sets,
            query_weights=query_weights,
            rrf_k=host.rrf_k,
            previous=previous_results if has_previous_ranking else None,
            previous_weight=previous_weight,
        )
    if result_sets:
        return list(result_sets[0])
    return []


async def run_retrieve(
    host: RetrievalHost,
    state: Any,
    groups: set[str],
    *,
    state_factory: Callable[..., Any],
) -> Any:
    """Execute multi-query retrieval, inject, select, and append trace attempts."""
    retrieval_queries = resolve_retrieval_queries(
        state.search_query,
        state.facet_queries,
        attempt=state.attempt,
    )
    frozen_groups = frozenset(groups)
    env = host.deployment_environment
    limit = retrieval_candidate_limit(host)

    result_sets = await _execute_multi_query_search(
        host,
        retrieval_queries,
        groups,
        frozen_groups=frozen_groups,
        environment=env,
        limit=limit,
        stage_timings_ms=state.stage_timings_ms,
    )
    results = _merge_retrieval_result_sets(
        host,
        result_sets,
        attempt=state.attempt,
        previous_results=state.results,
    )
    results = host.inject_enterprise_app_evidence(
        state.resolved_issue_query,
        results,
        groups=groups,
        environment=env,
    )
    results = await _maybe_rerank(
        host,
        query=state.resolved_issue_query or state.search_query,
        results=results,
    )
    competitive_results, displaced_top1 = host.select_document_chunks(
        state.resolved_issue_query, results
    )
    _append_trace_attempts(
        state.trace_attempts,
        retrieval_queries,
        result_sets,
        selected_chunk_ids={result.chunk.chunk_id for result in competitive_results},
    )
    return state_factory(
        raw_user_utterance=state.raw_user_utterance,
        resolved_issue_query=state.resolved_issue_query,
        search_query=state.search_query,
        facet_queries=state.facet_queries,
        results=competitive_results,
        raw_results=results,
        filter_displaced_top1=displaced_top1,
        trace_attempts=state.trace_attempts,
        attempt=state.attempt,
        stage_timings_ms=state.stage_timings_ms,
    )


__all__ = ["RetrievalHost", "retrieval_candidate_limit", "run_retrieve"]
