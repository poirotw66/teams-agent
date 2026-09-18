"""Retrieval stage orchestration extracted from HybridKnowledgeService."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from agent_service.retrieval import SearchResult

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

    async def _search_one(query: str) -> tuple[list[SearchResult], dict[str, float]]:
        cache_key = make_retrieval_cache_key(
            query,
            groups=frozen_groups,
            environment=env,
            release_id=host.release_id,
            top_k=host.top_k,
            min_score=host.min_score,
        )
        cache = host.retrieval_cache
        if cache_key in cache:
            if isinstance(cache, OrderedDict):
                cache.move_to_end(cache_key)
            return cache[cache_key], {}
        res, timings = await asyncio.to_thread(
            host.search_with_timings,
            query,
            host.top_k * RETRIEVAL_CANDIDATE_MULTIPLIER,
            groups,
            environment=env,
        )
        cache[cache_key] = res
        if len(cache) > MAX_RETRIEVAL_CACHE_SIZE and isinstance(cache, OrderedDict):
            cache.popitem(last=False)
        elif len(cache) > MAX_RETRIEVAL_CACHE_SIZE:
            # Non-OrderedDict fallback: drop an arbitrary oldest-ish key.
            cache.pop(next(iter(cache)))
        return res, timings

    search_outcomes = await asyncio.gather(*(_search_one(q) for q in retrieval_queries))
    result_sets = [outcome[0] for outcome in search_outcomes]
    for _results, timings in search_outcomes:
        accumulate_stage_timings(state.stage_timings_ms, timings)
    results = merge_best_chunk_results(*result_sets, previous=state.results)
    results = host.inject_enterprise_app_evidence(
        state.resolved_issue_query,
        results,
        groups=groups,
        environment=env,
    )
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


__all__ = ["RetrievalHost", "run_retrieve"]
