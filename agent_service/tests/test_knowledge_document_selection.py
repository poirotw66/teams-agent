"""Unit tests for knowledge document-selection policies."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.document_selection import (
    inject_enterprise_app_evidence,
    select_document_chunks,
)
from agent_service.retrieval import SearchResult


def _chunk(
    chunk_id: str,
    *,
    title: str = "doc",
    content: str = "body",
    document_id: str = "doc-1",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title=title,
        content=content,
        document_id=document_id,
        source_path=f"sources/{document_id}.md",
        allowed_groups=["IT"],
        content_state="ACTIVE",
        applicable_environments=["prod"],
    )


def _result(chunk: DocumentChunk, score: float) -> SearchResult:
    return SearchResult(chunk=chunk, score=score, sparse_score=score, dense_score=0.0)


def test_inject_enterprise_app_evidence_noop_without_query_terms() -> None:
    ad = _chunk("ad", title="AD", content="Outlook", document_id="ad")
    results = [_result(ad, 0.95)]
    boosted = inject_enterprise_app_evidence(
        "VPN 無法連線",
        results,
        index_chunks=[ad],
        groups={"IT"},
        environment="prod",
    )
    assert [item.chunk.chunk_id for item in boosted] == ["ad"]


def test_inject_enterprise_app_evidence_appends_trust_chunk() -> None:
    ad = _chunk("ad", title="AD", content="Outlook", document_id="ad")
    trust = _chunk(
        "trust",
        title="企業級APP",
        content="CATHAY LIFE verification",
        document_id="trust",
    )
    results = [_result(ad, 0.95)]
    boosted = inject_enterprise_app_evidence(
        "來源所述的企業 App 如何驗證？",
        results,
        index_chunks=[ad, trust],
        groups={"IT"},
        environment="prod",
    )
    ids = {item.chunk.chunk_id for item in boosted}
    assert "ad" in ids
    assert "trust" in ids


def test_inject_enterprise_app_evidence_preserves_ranking_order() -> None:
    """Injection must not re-sort by evidence score and wash out final_rank."""
    low_score_rrf_top = SearchResult(
        chunk=_chunk("rrf-top", title="AD", content="Outlook", document_id="ad"),
        score=0.40,
        sparse_score=0.40,
        dense_score=0.0,
        fusion_score=0.09,
        fusion_rank=1,
        final_rank=1,
    )
    high_score_second = SearchResult(
        chunk=_chunk("second", title="VPN", content="tunnel", document_id="vpn"),
        score=0.99,
        sparse_score=0.99,
        dense_score=0.0,
        fusion_score=0.05,
        fusion_rank=2,
        final_rank=2,
    )
    trust = _chunk(
        "trust",
        title="企業級APP",
        content="CATHAY LIFE verification",
        document_id="trust",
    )
    boosted = inject_enterprise_app_evidence(
        "來源所述的企業 App 如何驗證？",
        [low_score_rrf_top, high_score_second],
        index_chunks=[trust],
        groups={"IT"},
        environment="prod",
    )
    assert [item.chunk.chunk_id for item in boosted] == ["rrf-top", "second", "trust"]
    assert boosted[0].final_rank == 1
    assert boosted[1].final_rank == 2
    assert boosted[2].final_rank == 3
    assert boosted[2].score == 0.92


def test_inject_enterprise_app_evidence_boosts_score_without_reordering() -> None:
    """Existing trust hits may raise score for gates, but keep list order."""
    trust_low = SearchResult(
        chunk=_chunk(
            "trust",
            title="企業級APP",
            content="CATHAY LIFE verification",
            document_id="trust",
        ),
        score=0.50,
        sparse_score=0.50,
        dense_score=0.0,
        fusion_score=0.04,
        fusion_rank=2,
        final_rank=2,
    )
    other_high = SearchResult(
        chunk=_chunk("other", title="AD", content="Outlook", document_id="ad"),
        score=0.95,
        sparse_score=0.95,
        dense_score=0.0,
        fusion_score=0.10,
        fusion_rank=1,
        final_rank=1,
    )
    boosted = inject_enterprise_app_evidence(
        "企業級APP 驗證",
        [other_high, trust_low],
        index_chunks=[],
        groups={"IT"},
        environment="prod",
    )
    assert [item.chunk.chunk_id for item in boosted] == ["other", "trust"]
    assert boosted[0].score == 0.95
    assert boosted[1].score == 0.92
    assert boosted[1].final_rank == 2


def test_select_document_chunks_returns_empty_for_no_results() -> None:
    selected, displaced = select_document_chunks(
        "vpn",
        [],
        document_key=lambda result: result.chunk.document_id or result.chunk.chunk_id,
        index_chunks=[],
        top_k=3,
    )
    assert selected == []
    assert displaced is False
