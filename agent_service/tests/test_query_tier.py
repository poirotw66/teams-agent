"""Unit tests for adaptive post-retrieve query tiers."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.query_tier import QueryTier, classify_query_tier
from agent_service.knowledge_pipeline.retrieval_state import RetrievalState
from agent_service.retrieval import SearchResult


def _chunk(chunk_id: str, title: str, content: str = "") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source_path=f"{title}.md",
        title=title,
        content=content or title,
        allowed_groups=[],
    )


def _state(
    *,
    query: str,
    results: list[SearchResult],
    facet_queries: tuple[str, ...] = (),
    filter_displaced_top1: bool = False,
) -> RetrievalState:
    return RetrievalState(
        raw_user_utterance=query,
        resolved_issue_query=query,
        search_query=query,
        facet_queries=facet_queries,
        results=results,
        filter_displaced_top1=filter_displaced_top1,
    )


def test_high_confidence_lexical_hit_is_trivial() -> None:
    results = [
        SearchResult(
            chunk=_chunk("c1", "VPN 鎖住", "VPN 密碼鎖住 解鎖"),
            score=0.90,
            sparse_score=0.95,
        ),
        SearchResult(
            chunk=_chunk("c2", "其他", "無關內容"),
            score=0.50,
            sparse_score=0.40,
        ),
    ]
    decision = classify_query_tier(
        _state(query="VPN 密碼鎖住怎麼辦", results=results),
        min_score=0.08,
        max_retrieval_rewrites=1,
    )
    assert decision.tier == QueryTier.TRIVIAL
    assert decision.max_retrieval_rewrites == 0
    assert decision.enable_generation_retries is False


def test_mid_band_relevance_is_standard() -> None:
    results = [
        SearchResult(
            chunk=_chunk("c1", "一般說明", "系統操作說明"),
            score=0.70,
            sparse_score=0.50,
        ),
    ]
    decision = classify_query_tier(
        _state(query="這個怎麼設定", results=results),
        min_score=0.08,
        max_retrieval_rewrites=1,
    )
    assert decision.tier == QueryTier.STANDARD
    assert decision.max_retrieval_rewrites == 0
    assert decision.enable_generation_retries is False


def test_below_min_score_is_hard() -> None:
    results = [
        SearchResult(
            chunk=_chunk("c1", "無關", "完全不相關"),
            score=0.02,
            sparse_score=0.01,
        ),
    ]
    decision = classify_query_tier(
        _state(query="VPN 無法連線", results=results),
        min_score=0.08,
        max_retrieval_rewrites=1,
    )
    assert decision.tier == QueryTier.HARD
    assert decision.max_retrieval_rewrites == 1
    assert decision.enable_generation_retries is True


def test_multi_facet_query_is_hard_even_with_high_score() -> None:
    results = [
        SearchResult(
            chunk=_chunk("c1", "VPN 鎖住", "VPN 密碼鎖住"),
            score=0.92,
            sparse_score=0.95,
        ),
        SearchResult(
            chunk=_chunk("c2", "其他", "其他"),
            score=0.40,
            sparse_score=0.30,
        ),
    ]
    decision = classify_query_tier(
        _state(
            query="VPN 密碼鎖住怎麼辦",
            results=results,
            facet_queries=("facet-a", "facet-b"),
        ),
        min_score=0.08,
        max_retrieval_rewrites=2,
    )
    assert decision.tier == QueryTier.HARD
    assert decision.max_retrieval_rewrites == 2


def test_displaced_top1_is_hard() -> None:
    results = [
        SearchResult(
            chunk=_chunk("c1", "VPN 鎖住", "VPN 密碼鎖住"),
            score=0.90,
            sparse_score=0.95,
        ),
    ]
    decision = classify_query_tier(
        _state(
            query="VPN 密碼鎖住怎麼辦",
            results=results,
            filter_displaced_top1=True,
        ),
        min_score=0.08,
        max_retrieval_rewrites=1,
    )
    assert decision.tier == QueryTier.HARD
