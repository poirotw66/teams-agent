"""Retrieval stage orchestration extracted from HybridKnowledgeService."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Mapping, MutableMapping
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
    make_retrieval_cache_key,
    merge_best_chunk_results,
    resolve_retrieval_queries,
)
from .trace import build_retrieval_attempt


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
            environment=environment,
            fusion_mode=host.fusion_mode,
        )
    cache[cache_key] = res
    if len(cache) > MAX_RETRIEVAL_CACHE_SIZE and isinstance(cache, OrderedDict):
        cache.popitem(last=False)
    elif len(cache) > MAX_RETRIEVAL_CACHE_SIZE:
        cache.pop(next(iter(cache)))
    return res, timings


async def _maybe_rerank(
    host: RetrievalHost,
    *,
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    if not host.reranker_enabled or host.reranker is None or not results:
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
    search_outcomes = await asyncio.gather(
        *(
            _cached_search(
                host,
                query,
                groups=groups,
                frozen_groups=frozen_groups,
                environment=env,
            )
            for query in retrieval_queries
        )
    )
    result_sets = [outcome[0] for outcome in search_outcomes]
    for _results, timings in search_outcomes:
        accumulate_stage_timings(state.stage_timings_ms, timings)
    results = merge_best_chunk_results(*result_sets, previous=state.results)
    # Injection is a retriever-like signal: it must enter the pool before rerank
    # so enterprise evidence is ranked, not force-inserted after (RAG v2.1 P2).
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
    # Ranking ends here. Parent/neighbor expansion happens after selection
    # via EvidenceBundle in the generation stage (does not re-order hits).
    competitive_results, displaced_top1 = host.select_document_chunks(
        state.resolved_issue_query, results
    )
    selected_chunk_ids = {result.chunk.chunk_id for result in competitive_results}
    for retrieval_query, result_set in zip(
        retrieval_queries,
        result_sets,
        strict=True,
    ):
        state.trace_attempts.append(
            build_retrieval_attempt(
                retrieval_query,
                result_set,
                selected_chunk_ids,
            )
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
