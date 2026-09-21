"""Tests for source-role assignment and incidental filtering."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.source_roles import (
    SourceRole,
    assign_source_roles,
    filter_results_for_generation,
)
from agent_service.retrieval import SearchResult


def _result(doc_key: str, title: str, content: str) -> SearchResult:
    return SearchResult(
        chunk=DocumentChunk(
            chunk_id=doc_key,
            title=title,
            content=content,
            document_id=doc_key,
            source_path=f"sources/{doc_key}.md",
        ),
        score=0.9,
        sparse_score=0.9,
        dense_score=0.0,
    )


def test_assign_source_roles_marks_peripheral_doc_incidental() -> None:
    results = [
        _result("jump", "VPN 跳板機連線異常", "跳板機遠端桌面無法連線時請轉派工單"),
        _result("vpn", "內網筆電 VPN 連線問題", "FortiClient 連線後無法進入內網"),
        _result("ad", "AD 帳號與系統解鎖 FAQ", "AD 帳號鎖定請自助解鎖"),
    ]
    roles = assign_source_roles(
        query="跳板機連不上",
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert roles["jump"] == SourceRole.PRIMARY
    assert roles["ad"] == SourceRole.INCIDENTAL


def test_filter_results_for_generation_drops_incidental() -> None:
    results = [
        _result("crm", "外網 CRM 登入連線設定方式", "外網 CRM FortiToken 連線設定"),
        _result("ad", "AD 帳號與系統解鎖 FAQ", "系統清單含 CRM；AD 鎖定請自助解鎖"),
    ]
    filtered = filter_results_for_generation(
        query="外網 CRM 連線設定",
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    keys = [result.chunk.document_id for result in filtered]
    assert keys == ["crm"]


def test_latin_product_token_beats_generic_unlock_vocab() -> None:
    """Regression: Gitlab unlock must not be dropped for AD FAQ on 解鎖 overlap."""
    results = [
        _result("gitlab", "Gitlab帳號解鎖跟重置", "Gitlab 帳號被鎖請找資訊單位解鎖"),
        _result("ad", "AD 帳號與系統解鎖 FAQ", "AD 帳號鎖定請使用自助解鎖專區"),
    ]
    roles = assign_source_roles(
        query="Gitlab 帳號被鎖可以找誰解鎖？",
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert roles["gitlab"] == SourceRole.PRIMARY
    assert roles["ad"] != SourceRole.PRIMARY


def test_filter_results_for_generation_packs_primary_before_supporting() -> None:
    results = [
        _result("support", "外網 CRM 登入連線設定方式", "外網 CRM FortiToken OTP 也可綁定"),
        _result("primary", "國金 CRM OTP 綁訂操作", "Google Authenticator 首次登入需使用 OTP Key"),
    ]
    filtered = filter_results_for_generation(
        query="OTP 綁定操作，不是外網連線設定",
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    keys = [result.chunk.document_id for result in filtered]
    assert keys[0] == "primary"
    assert "support" not in keys


def test_contrastive_query_prefers_positive_topic_over_negated_doc() -> None:
    """Regression: 不是功能無法點選那篇 must keep 首次設定, not the negated doc."""
    results = [
        _result("broken", "大州系統_功能無法點選", "功能無法點選時請檢查相容性檢視"),
        _result(
            "first",
            "大州首次使用設定",
            "首次設定請開啟網際網路選項並設為每次造訪網頁時",
        ),
    ]
    filtered = filter_results_for_generation(
        query="大州首次設定，不是功能無法點選那篇",
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    keys = [result.chunk.document_id for result in filtered]
    assert "first" in keys
    assert "broken" not in keys


def test_filter_rescues_top_score_when_latin_boost_marks_it_incidental() -> None:
    """Rewrite-injected Outlook must not drop the score=1.0 郵件為亂碼 seed."""
    garbled = SearchResult(
        chunk=DocumentChunk(
            chunk_id="garbled",
            title="郵件為亂碼",
            content="點開發出的電郵，選取繁體中文(Big 5)或 Unicode(UTF-8)",
            document_id="garbled",
            source_path="sources/garbled.md",
        ),
        score=1.0,
        sparse_score=1.0,
        dense_score=0.0,
    )
    outlook = SearchResult(
        chunk=DocumentChunk(
            chunk_id="outlook",
            title="行動裝置 Outlook 安裝手冊（iOS）",
            content="iPhone 收公司信請安裝 Outlook 與 Authenticator",
            document_id="outlook",
            source_path="sources/outlook.md",
        ),
        score=0.58,
        sparse_score=0.58,
        dense_score=0.0,
    )
    filtered = filter_results_for_generation(
        query="信件 亂碼 轉回 正常 編碼 Outlook",
        results=[garbled, outlook],
        document_key=lambda result: result.chunk.document_id or "",
    )
    keys = [result.chunk.document_id for result in filtered]
    assert keys[0] == "garbled"
    assert "outlook" in keys or keys == ["garbled"]
