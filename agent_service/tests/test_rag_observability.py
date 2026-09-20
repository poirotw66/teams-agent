"""Tests for RAG v2 observability helpers (spec §36–§38)."""

from __future__ import annotations

import pytest

from agent_service.rag_observability import (
    record_cache_hit,
    record_query_tier,
    record_relevance_deterministic_skip,
    record_relevance_llm_outcome,
    reset_counters,
    snapshot_counters,
)
from agent_service.reranker import FailOpenReranker, NoopReranker
from agent_service.retrieval import SearchResult
from knowledge_core.document_models import DocumentChunk


def setup_function() -> None:
    reset_counters()


def test_cache_and_tier_counters() -> None:
    record_cache_hit(True)
    record_cache_hit(False)
    record_query_tier("hard")
    snap = snapshot_counters()
    assert snap["rag_retrieval_cache_hits"] == 1.0
    assert snap["rag_retrieval_cache_misses"] == 1.0
    assert snap["rag_query_tier_hard"] == 1.0


def test_relevance_llm_audit_counters() -> None:
    record_relevance_deterministic_skip()
    record_relevance_llm_outcome(deterministic_relevant=True, llm_relevant=True)
    record_relevance_llm_outcome(deterministic_relevant=True, llm_relevant=False)
    snap = snapshot_counters()
    assert snap["rag_relevance_deterministic_skips"] == 1.0
    assert snap["rag_relevance_llm_calls"] == 2.0
    assert snap["rag_relevance_llm_unchanged"] == 1.0
    assert snap["rag_relevance_llm_flipped"] == 1.0


@pytest.mark.asyncio
async def test_fail_open_increments_timeout_counter() -> None:
    class Slow:
        async def rerank(self, *, query: str, candidates: list[SearchResult], limit: int):
            import asyncio

            await asyncio.sleep(1.0)
            return candidates

    chunk = DocumentChunk(
        chunk_id="c1",
        title="t",
        source_path="t.md",
        content="body",
    )
    candidates = [SearchResult(chunk=chunk, score=1.0, sparse_score=1.0)]
    await FailOpenReranker(Slow(), timeout_seconds=0.01, fallback=NoopReranker()).rerank(
        query="q",
        candidates=candidates,
        limit=1,
    )
    assert snapshot_counters()["rag_reranker_timeout_total"] == 1.0
