"""樹精靈 AP vs WEB channel isolation and AP-manual inject."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.candidate_policy import filter_cross_scenario_chunks
from agent_service.knowledge_pipeline.document_selection import (
    inject_shu_channel_evidence,
    select_document_chunks,
)
from agent_service.retrieval import SearchResult


def _chunk(
    chunk_id: str,
    *,
    title: str,
    content: str,
    document_id: str,
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


def _result(chunk: DocumentChunk, score: float, *, rank: int = 1) -> SearchResult:
    return SearchResult(
        chunk=chunk,
        score=score,
        sparse_score=score,
        dense_score=0.0,
        final_rank=rank,
    )


def _ap_chunk() -> DocumentChunk:
    return _chunk(
        "ap-1",
        title="樹精靈AP無法登入",
        content="網路錯誤12029，請調整 TLS 與停用 Proxy。",
        document_id="doc-ap",
    )


def _web_chunk() -> DocumentChunk:
    return _chunk(
        "web-1",
        title="樹精靈WEB-登入異常.無法登入.登入無反映.畫面無反應",
        content="安控元件狀態無回應時請點選離開後重開網頁。",
        document_id="doc-web",
    )


def _document_key(result: SearchResult) -> str:
    return result.chunk.document_id or result.chunk.chunk_id


def test_ap_login_query_drops_web_handbook() -> None:
    filtered = filter_cross_scenario_chunks(
        "樹精靈 AP 無法登入",
        [_result(_web_chunk(), 0.96, rank=1), _result(_ap_chunk(), 0.80, rank=2)],
    )
    titles = [item.chunk.title for item in filtered]
    assert "樹精靈AP無法登入" in titles
    assert all("WEB" not in title for title in titles)


def test_web_login_query_drops_ap_handbook() -> None:
    filtered = filter_cross_scenario_chunks(
        "樹精靈 WEB-登入異常",
        [_result(_ap_chunk(), 0.96, rank=1), _result(_web_chunk(), 0.80, rank=2)],
    )
    titles = [item.chunk.title for item in filtered]
    assert any("WEB" in title for title in titles)
    assert "樹精靈AP無法登入" not in titles


def test_comparison_query_keeps_ap_and_web() -> None:
    filtered = filter_cross_scenario_chunks(
        "樹精靈 AP 和 樹精靈 WEB 登入差在哪",
        [_result(_ap_chunk(), 0.90, rank=1), _result(_web_chunk(), 0.88, rank=2)],
    )
    titles = {item.chunk.title for item in filtered}
    assert "樹精靈AP無法登入" in titles
    assert any("WEB" in title for title in titles)


def test_inject_ap_manual_for_ap_only_query() -> None:
    web = _web_chunk()
    ap = _ap_chunk()
    boosted = inject_shu_channel_evidence(
        "樹精靈AP無法登入",
        [_result(web, 0.95, rank=1)],
        index_chunks=[web, ap],
        groups={"IT"},
        environment="prod",
    )
    assert any(item.chunk.document_id == "doc-ap" for item in boosted)


def test_select_does_not_reinsert_web_as_raw_top1_for_ap_query() -> None:
    web = _web_chunk()
    ap = _ap_chunk()
    selected, _ = select_document_chunks(
        "樹精靈 AP 無法登入",
        [_result(web, 0.97, rank=1), _result(ap, 0.81, rank=2)],
        document_key=_document_key,
        index_chunks=[web, ap],
        top_k=3,
    )
    titles = [item.chunk.title for item in selected]
    assert titles
    assert all("WEB" not in title for title in titles)
    assert any("樹精靈AP無法登入" == title for title in titles)
