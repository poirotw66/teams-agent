"""Regression tests for SearchResult ranking contract."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.document_selection_select import (
    rank_documents_for_query,
)
from agent_service.knowledge_pipeline.retriever import merge_best_chunk_results
from agent_service.retrieval import SearchResult


def _chunk(chunk_id: str, *, document_id: str = "doc", title: str = "t") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title=title,
        source_path=f"{document_id}.md",
        content=f"body-{chunk_id}",
        document_id=document_id,
    )


def _hit(
    chunk_id: str,
    *,
    score: float,
    document_id: str = "doc",
    fusion_score: float | None = None,
    fusion_rank: int | None = None,
    rerank_score: float | None = None,
    rerank_rank: int | None = None,
    final_rank: int | None = None,
) -> SearchResult:
    return SearchResult(
        chunk=_chunk(chunk_id, document_id=document_id),
        score=score,
        sparse_score=score,
        dense_score=score,
        fusion_score=fusion_score,
        fusion_rank=fusion_rank,
        rerank_score=rerank_score,
        rerank_rank=rerank_rank,
        final_rank=final_rank,
    )


def test_rrf_top1_survives_merge_despite_lower_evidence_score() -> None:
    """RRF rank-1 must stay top after merge even if evidence confidence is lower."""
    rrf_top = _hit(
        "a",
        score=0.40,
        fusion_score=0.09,
        fusion_rank=1,
        final_rank=1,
    )
    rrf_second = _hit(
        "b",
        score=0.95,
        fusion_score=0.05,
        fusion_rank=2,
        final_rank=2,
    )
    merged = merge_best_chunk_results([rrf_top, rrf_second])
    assert [item.chunk.chunk_id for item in merged] == ["a", "b"]


def test_reranker_promotion_survives_document_selection() -> None:
    """Document selection must follow rerank order, not legacy evidence score."""
    low_evidence_winner = _hit(
        "b",
        score=0.30,
        document_id="doc-b",
        rerank_score=0.99,
        rerank_rank=1,
        final_rank=1,
    )
    high_evidence_loser = _hit(
        "a",
        score=0.95,
        document_id="doc-a",
        rerank_score=0.10,
        rerank_rank=2,
        final_rank=2,
    )
    ranked = rank_documents_for_query(
        "query",
        [low_evidence_winner, high_evidence_loser],
        document_key=lambda item: item.chunk.document_id or item.chunk.source_path,
        top_k=3,
    )
    assert ranked[0][0].chunk.chunk_id == "b"


def test_multi_query_merge_preserves_fusion_ranking() -> None:
    """Multi-query merge must keep RRF ordering across query result sets."""
    query_a = [
        _hit("keep", score=0.2, fusion_score=0.08, fusion_rank=1, final_rank=1),
        _hit("other", score=0.9, fusion_score=0.04, fusion_rank=2, final_rank=2),
    ]
    query_b = [
        _hit("keep", score=0.15, fusion_score=0.07, fusion_rank=1, final_rank=1),
        _hit("tail", score=0.99, fusion_score=0.02, fusion_rank=3, final_rank=3),
    ]
    merged = merge_best_chunk_results(query_a, query_b)
    assert merged[0].chunk.chunk_id == "keep"
    assert [item.chunk.chunk_id for item in merged] == ["keep", "other", "tail"]
