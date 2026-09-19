"""Tests for Soft / listwise title-protect blend (RAG v2 §45 path)."""

from __future__ import annotations

import pytest

from agent_service.documents import DocumentChunk
from agent_service.reranker import (
    ModelReranker,
    TitleProtectedListwiseReranker,
    parse_listwise_order_payload,
    scores_from_listwise_order,
)
from agent_service.retrieval import SearchResult
from agent_service.retrieval_blend import (
    blend_soft_and_listwise_top1,
    should_keep_soft_top,
    title_token_coverage,
)


def _result(chunk_id: str, *, title: str, content: str = "body") -> SearchResult:
    return SearchResult(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            title=title,
            source_path=f"{chunk_id}.md",
            content=content,
            retrieval_text=content,
        ),
        score=1.0,
        sparse_score=1.0,
        dense_score=0.5,
    )


def test_title_coverage_prefers_jumpbox_title() -> None:
    query = "跳板機授權狀態要怎麼第一層判斷"
    soft = "VPN 跳板機連線異常"
    other = "登入 FortiClient 出現錯訊"
    assert title_token_coverage(query, soft) > title_token_coverage(query, other)
    assert should_keep_soft_top(query=query, soft_title=soft, listwise_title=other)


def test_generic_soft_title_does_not_block_listwise() -> None:
    query = "客戶說報價下單怪怪的要怎麼判斷是不是廠商問題"
    soft = "外部客戶線上問題"
    listwise = "XQ問題"
    assert not should_keep_soft_top(
        query=query, soft_title=soft, listwise_title=listwise
    )


def test_authenticator_keeps_soft_otp_title() -> None:
    query = "Authenticator 出現六位數後要回到哪個畫面"
    soft = "國金 CRM OTP 綁訂操作"
    listwise = "VPN常見Q&A問答"
    assert should_keep_soft_top(query=query, soft_title=soft, listwise_title=listwise)


def test_blend_promotes_listwise_when_not_protected() -> None:
    soft = [
        _result("crm", title="外網 CRM 登入連線設定方式"),
        _result("vpn", title="VPN常見Q&A問答"),
    ]
    blended = blend_soft_and_listwise_top1(
        query="FortiToken 收不到 OTP",
        soft_ranked=soft,
        listwise_top=soft[1],
    )
    assert blended[0].chunk.chunk_id == "vpn"


def test_blend_keeps_soft_when_protected() -> None:
    soft = [
        _result("jump", title="VPN 跳板機連線異常"),
        _result("forti", title="登入 FortiClient 出現錯訊"),
    ]
    blended = blend_soft_and_listwise_top1(
        query="跳板機授權狀態要怎麼第一層判斷",
        soft_ranked=soft,
        listwise_top=soft[1],
    )
    assert blended[0].chunk.chunk_id == "jump"


def test_parse_listwise_order_accepts_int_array_and_objects() -> None:
    assert parse_listwise_order_payload("[3,1,2]", 3) == [3, 1, 2]
    assert parse_listwise_order_payload(
        '[{"id":2,"title":"a"},{"id":1,"title":"b"}]', 2
    ) == [2, 1]
    assert scores_from_listwise_order(3, [2, 1, 3])[1] == 3.0


@pytest.mark.asyncio
async def test_title_protected_listwise_reranker_blends() -> None:
    soft = [
        _result("crm", title="外網 CRM 登入連線設定方式", content="外網 CRM 登入連線設定方式"),
        _result("vpn", title="VPN常見Q&A問答", content="VPN常見Q&A問答 FortiToken OTP"),
    ]

    async def prefer_vpn(query: str, texts: list[str]) -> list[float]:
        del query
        return [0.9 if "FortiToken" in text or "VPN" in text else 0.1 for text in texts]

    reranker = TitleProtectedListwiseReranker(ModelReranker(prefer_vpn))
    ranked = await reranker.rerank(
        query="FortiToken 收不到 OTP",
        candidates=soft,
        limit=2,
    )
    assert ranked[0].chunk.chunk_id == "vpn"


def test_build_default_reranker_listwise_uses_title_protect() -> None:
    from agent_service.reranker import FailOpenReranker, build_default_reranker

    reranker = build_default_reranker(
        enabled=True,
        timeout_ms=700,
        model_name="listwise",
    )
    assert isinstance(reranker, FailOpenReranker)
    assert isinstance(reranker._inner, TitleProtectedListwiseReranker)
