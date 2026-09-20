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


def test_select_document_chunks_diversity_first_across_two_docs() -> None:
    """Comparison queries interleave one chunk per document before filling."""
    results = [
        SearchResult(
            chunk=_chunk("a1", title="Outlook iOS 手冊", document_id="ios", content="a1"),
            score=0.95,
            sparse_score=0.95,
            dense_score=0.0,
            final_rank=1,
            fusion_rank=1,
        ),
        SearchResult(
            chunk=_chunk("a2", title="Outlook iOS 手冊", document_id="ios", content="a2"),
            score=0.94,
            sparse_score=0.94,
            dense_score=0.0,
            final_rank=2,
            fusion_rank=2,
        ),
        SearchResult(
            chunk=_chunk(
                "b1", title="Outlook Android 手冊", document_id="android", content="b1"
            ),
            score=0.93,
            sparse_score=0.93,
            dense_score=0.0,
            final_rank=3,
            fusion_rank=3,
        ),
        SearchResult(
            chunk=_chunk(
                "b2", title="Outlook Android 手冊", document_id="android", content="b2"
            ),
            score=0.92,
            sparse_score=0.92,
            dense_score=0.0,
            final_rank=4,
            fusion_rank=4,
        ),
    ]
    selected, _ = select_document_chunks(
        "Outlook iOS 與 Android 綁定步驟有何不同",
        results,
        document_key=lambda result: result.chunk.document_id or result.chunk.chunk_id,
        index_chunks=[],
        top_k=4,
    )
    top4_docs = [item.chunk.document_id for item in selected[:4]]
    assert top4_docs.count("ios") >= 1
    assert top4_docs.count("android") >= 1
    assert top4_docs[:2] == ["ios", "android"]


def test_select_document_chunks_keeps_contiguous_fill_for_short_queries() -> None:
    """Non-comparison short queries keep per-doc contiguous fill for exact hits."""
    results = [
        SearchResult(
            chunk=_chunk("a1", title="VPN常見Q&A問答", document_id="vpn", content="-20199"),
            score=0.95,
            sparse_score=0.95,
            dense_score=0.0,
            final_rank=1,
        ),
        SearchResult(
            chunk=_chunk("a2", title="VPN常見Q&A問答", document_id="vpn", content="other"),
            score=0.94,
            sparse_score=0.94,
            dense_score=0.0,
            final_rank=2,
        ),
        SearchResult(
            chunk=_chunk("b1", title="內網筆電 VPN", document_id="laptop", content="b1"),
            score=0.93,
            sparse_score=0.93,
            dense_score=0.0,
            final_rank=3,
        ),
    ]
    selected, _ = select_document_chunks(
        "Unable to establish VPN (-20199)",
        results,
        document_key=lambda result: result.chunk.document_id or result.chunk.chunk_id,
        index_chunks=[],
        top_k=4,
    )
    assert [item.chunk.chunk_id for item in selected[:3]] == ["a1", "a2", "b1"]


def test_multi_doc_procedure_query_keeps_both_manuals() -> None:
    def _manual_chunk(
        chunk_id: str,
        *,
        document_id: str,
        title: str,
        section: str,
    ) -> DocumentChunk:
        return DocumentChunk(
            chunk_id=chunk_id,
            title=title,
            content=section,
            document_id=document_id,
            source_path=f"sources/{document_id}.md",
            section=section,
            allowed_groups=["IT"],
            content_state="ACTIVE",
            applicable_environments=["prod"],
        )

    ios_title = "行動裝置 Outlook 安裝手冊（iOS）"
    android_title = "行動裝置 Outlook 安裝手冊（Android）"
    results = [
        SearchResult(
            chunk=_manual_chunk("ios-1", document_id="ios", title=ios_title, section="1. 驗證"),
            score=0.95,
            sparse_score=0.95,
            dense_score=0.0,
            final_rank=1,
        ),
        SearchResult(
            chunk=_manual_chunk("ios-2", document_id="ios", title=ios_title, section="2. 綁定"),
            score=0.94,
            sparse_score=0.94,
            dense_score=0.0,
            final_rank=2,
        ),
        SearchResult(
            chunk=_manual_chunk(
                "and-1", document_id="android", title=android_title, section="1. 驗證"
            ),
            score=0.93,
            sparse_score=0.93,
            dense_score=0.0,
            final_rank=3,
        ),
        SearchResult(
            chunk=_manual_chunk(
                "and-2", document_id="android", title=android_title, section="2. 綁定"
            ),
            score=0.92,
            sparse_score=0.92,
            dense_score=0.0,
            final_rank=4,
        ),
    ]
    selected, _ = select_document_chunks(
        "Outlook 手冊 iOS 與 Android 綁定步驟不同之處",
        results,
        document_key=lambda result: result.chunk.document_id or result.chunk.chunk_id,
        index_chunks=[item.chunk for item in results],
        top_k=4,
    )
    titles = {item.chunk.title for item in selected[:4]}
    assert any("iOS" in title for title in titles)
    assert any("Android" in title for title in titles)


def test_comparison_external_query_keeps_internal_sibling() -> None:
    from agent_service.knowledge_pipeline.candidate_policy_filters import (
        apply_audience_isolation,
    )
    from agent_service.knowledge_pipeline.candidate_policy_intents import (
        detect_query_intent_flags,
    )

    internal = _result(
        _chunk("int", title="資訊問題的通報格式", document_id="report", content="主旨"),
        0.95,
    )
    external = _result(
        _chunk("ext", title="外部客戶線上問題如何回報", document_id="ext", content="欄位"),
        0.94,
    )
    intent = detect_query_intent_flags("通報主旨格式與外部客戶回報欄位有何不同")
    kept = apply_audience_isolation([internal, external], intent)
    ids = {item.chunk.chunk_id for item in kept}
    assert ids == {"int", "ext"}
