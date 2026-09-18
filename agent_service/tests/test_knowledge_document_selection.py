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
