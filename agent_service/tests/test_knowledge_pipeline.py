"""Unit tests for pure knowledge_pipeline helpers."""

from __future__ import annotations

from agent_service.contracts import GroundedClaim, KnowledgeResult, PolicyAdvisory
from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline import (
    attach_retrieval_trace,
    bounded_facet_queries,
    build_retrieval_attempt,
    evaluate_retrieval_confidence,
    filter_cross_scenario_chunks,
    is_non_production_knowledge_chunk,
    merge_best_chunk_results,
    merge_policy_advisories,
    missing_diagnosis_facet_queries,
    normalize_composite_citation_markers,
    remap_claim_marker_ids_to_chunk_ids,
    repair_structured_answer,
    resolve_retrieval_queries,
    sanitize_answer_security,
)
from agent_service.knowledge_pipeline.models import StructuredKnowledgeAnswer
from agent_service.retrieval import SearchResult


def _chunk(
    *,
    chunk_id: str,
    title: str,
    content: str,
    section: str | None = None,
    source_path: str | None = None,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        title=title,
        content=content,
        section=section,
        source_path=source_path,
    )


def _result(chunk: DocumentChunk, score: float = 0.9) -> SearchResult:
    return SearchResult(chunk=chunk, score=score, sparse_score=score, dense_score=0.0)


def test_bounded_facet_queries_and_diagnosis_followups() -> None:
    facets = bounded_facet_queries("PortalX 的申請方式、核准人、處理時間與必要資料有哪些？")
    assert facets[:3] == (
        "PortalX 申請方式",
        "PortalX 核准人",
        "PortalX 處理時間",
    )
    missing = missing_diagnosis_facet_queries(
        "FortiClient 是版本、網路還是設定問題？",
        "請先確認網路熱點與 Wi-Fi 連線是否正常。",
    )
    assert any("版本" in query for query in missing)
    assert not any(query.endswith(" 網路") for query in missing)


def test_filter_cross_scenario_keeps_matching_faq_scenario() -> None:
    quote = _result(_chunk(chunk_id="q1", title="報價問題 FAQ-004", content="五檔行情"))
    trade = _result(_chunk(chunk_id="t1", title="交易問題 FAQ-002", content="下單委託"))
    filtered = filter_cross_scenario_chunks("報價五檔怎麼看？", [quote, trade])
    assert [item.chunk.chunk_id for item in filtered] == ["q1"]


def test_is_non_production_knowledge_chunk() -> None:
    assert is_non_production_knowledge_chunk(
        _chunk(chunk_id="x", title="[UX-AUDIT] draft", content="x")
    )
    assert not is_non_production_knowledge_chunk(
        _chunk(chunk_id="y", title="正式 FAQ", content="y")
    )


def test_normalize_and_remap_claim_markers() -> None:
    assert normalize_composite_citation_markers("步驟完成 [S2, S3]。") == "步驟完成 [S2][S3]。"
    remapped = remap_claim_marker_ids_to_chunk_ids(
        [GroundedClaim(text="請重啟 Outlook 客戶端", chunkIds=["S1"])],
        marker_to_chunk_ids={"S1": ["c1", "c2"]},
        chunk_content_by_id={
            "c1": "請重啟 Outlook 客戶端後再試",
            "c2": "無關的電話分機說明",
        },
    )
    assert remapped == [
        GroundedClaim(text="請重啟 Outlook 客戶端", chunkIds=["c1"]),
    ]


def test_repair_structured_answer_aligns_answerability() -> None:
    repaired = repair_structured_answer(
        StructuredKnowledgeAnswer(
            answerability="NONE",
            answer="有答案",
            claims=[GroundedClaim(text="事實", chunkIds=["c1"])],
            unknowns=[],
        )
    )
    assert repaired.answerability == "FULL"


def test_sanitize_answer_security_redacts_placeholder_url() -> None:
    sanitized = sanitize_answer_security("請前往 https://demo.pages.dev/vpn 設定。")
    assert "pages.dev" not in sanitized
    assert "測試連結" in sanitized


def test_merge_policy_advisories_dedupes_by_policy_ids() -> None:
    first = PolicyAdvisory(policyIds=["POLICY-SEC-001"], text="a")
    second = PolicyAdvisory(policyIds=["POLICY-SEC-001"], text="b")
    third = PolicyAdvisory(policyIds=["POLICY-SEC-002"], text="c")
    merged = merge_policy_advisories([first, second], [third])
    assert [item.policyIds for item in merged] == [
        ["POLICY-SEC-001"],
        ["POLICY-SEC-002"],
    ]


def test_evaluate_retrieval_confidence_blocks_displaced_top1() -> None:
    hit = _result(_chunk(chunk_id="c1", title="VPN 指南", content="VPN 密碼解鎖"), score=0.9)
    label, is_deterministic = evaluate_retrieval_confidence(
        query="VPN 密碼被鎖",
        results=[hit],
        min_score=0.05,
        filter_displaced_top1=True,
    )
    assert label == "LLM_RELEVANCE"
    assert is_deterministic is False


def test_resolve_and_merge_retrieval_helpers() -> None:
    assert resolve_retrieval_queries("q1", ("f1", "q1"), attempt=0) == ("q1", "f1")
    assert resolve_retrieval_queries("q1", ("f1",), attempt=1) == ("q1",)
    weaker = _result(_chunk(chunk_id="c1", title="a", content="a"), score=0.4)
    stronger = _result(_chunk(chunk_id="c1", title="a", content="a"), score=0.8)
    other = _result(_chunk(chunk_id="c2", title="b", content="b"), score=0.5)
    merged = merge_best_chunk_results([weaker, other], [stronger], previous=[])
    assert [item.chunk.chunk_id for item in merged] == ["c1", "c2"]
    assert merged[0].score == 0.8


def test_attach_retrieval_trace_and_attempt_builders() -> None:
    hit = _result(_chunk(chunk_id="c1", title="t", content="body"), score=0.7)
    attempt = build_retrieval_attempt("vpn lock", [hit], {"c1"})
    assert attempt.candidates[0].selectedForContext is True
    result = KnowledgeResult(found=False, answer="", sources=[], images=[], backend="HYBRID")
    traced = attach_retrieval_trace(
        result,
        raw_user_utterance="raw",
        resolved_issue_query="resolved",
        search_query="search",
        facet_queries=("f1",),
        selected_backend=None,
        attempts=[attempt],
        stage_timings_ms={"retrievalMs": 1.0},
        fallback_path="NO_RELEVANT_EVIDENCE",
        terminal_reason="NO_RELEVANT_EVIDENCE",
    )
    assert traced.terminalReason == "NO_RELEVANT_EVIDENCE"
    assert traced.retrievalTrace is not None
    assert traced.retrievalTrace.selectedBackend == "HYBRID"
