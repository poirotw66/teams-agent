"""Tests for query-aligned citation pruning."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.generation_stage_result import (
    prefer_query_aligned_citations,
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


def test_prefer_query_aligned_citations_drops_peripheral_source() -> None:
    results = [
        _result("jump", "VPN 跳板機連線異常", "跳板機遠端桌面無法連線時請轉派工單"),
        _result("vpn", "內網筆電 VPN 連線問題", "FortiClient 連線後無法進入內網"),
    ]
    kept = prefer_query_aligned_citations(
        query="跳板機連不上",
        ordered_cited_doc_keys=["jump", "vpn"],
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert kept == ["jump"]


def test_prefer_query_aligned_citations_keeps_near_equal_supporting_docs() -> None:
    results = [
        _result(
            "shared",
            "公槽申請手冊",
            "提出共用公槽人員新增或移除申請時，聯繫單應填寫必要資料。",
        ),
        _result(
            "security",
            "共用公槽資安手冊",
            "提出共用公槽人員新增申請時不可將個人機敏資訊填入聯繫單。",
        ),
    ]
    kept = prefer_query_aligned_citations(
        query="提出共用公槽人員新增申請時應填寫哪些資料",
        ordered_cited_doc_keys=["shared", "security"],
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert kept == ["shared", "security"]


def test_prefer_query_aligned_citations_keeps_single_source() -> None:
    results = [_result("ad", "AD 帳號與系統解鎖 FAQ", "AD 帳號鎖定請自助解鎖")]
    kept = prefer_query_aligned_citations(
        query="AD 鎖定",
        ordered_cited_doc_keys=["ad"],
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert kept == ["ad"]


def test_drop_ad_unlock_citations_for_crm_otp_query() -> None:
    from agent_service.knowledge_pipeline.generation_stage_result import (
        drop_ad_unlock_citations_for_product_query,
    )

    results = [
        _result("crm", "國金 CRM OTP 綁訂操作", "Google Authenticator OTP 綁定"),
        _result("ext", "外網 CRM 登入連線設定方式", "FortiToken App 掃描 QR Code"),
        _result("ad", "AD 帳號與系統解鎖 FAQ", "CRM 系統清單含國金 CRM；AD 鎖定請自助解鎖"),
    ]
    kept, common = drop_ad_unlock_citations_for_product_query(
        query="CRM OTP",
        ordered_cited_doc_keys=["crm", "ext", "ad"],
        common_doc_keys={"crm", "ext", "ad"},
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert kept == ["crm", "ext"]
    assert common == {"crm", "ext"}


def test_drop_ad_unlock_citations_for_non_ad_vpn_query() -> None:
    from agent_service.knowledge_pipeline.generation_stage_result import (
        drop_ad_unlock_citations_for_product_query,
    )

    results = [
        _result("forti", "登入 FortiClient 出現錯訊", "錯誤碼 -455 Permission denied"),
        _result("vpn", "VPN常見Q&A問答", "VPN 密碼輸入錯誤請重試"),
        _result("ad", "AD 帳號與系統解鎖 FAQ", "AD 帳號鎖定請自助解鎖"),
    ]
    kept, common = drop_ad_unlock_citations_for_product_query(
        query="FortiClient Permission denied 錯誤碼 -455",
        ordered_cited_doc_keys=["forti", "vpn", "ad"],
        common_doc_keys={"forti", "vpn", "ad"},
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert kept == ["forti", "vpn"]
    assert common == {"forti", "vpn"}


def test_drop_ad_unlock_citations_keeps_ad_for_lock_query() -> None:
    from agent_service.knowledge_pipeline.generation_stage_result import (
        drop_ad_unlock_citations_for_product_query,
    )

    results = [
        _result("ad", "AD 帳號與系統解鎖 FAQ", "AD 帳號鎖定請自助解鎖"),
        _result("vpn", "VPN常見Q&A問答", "AD 帳號是否被鎖"),
    ]
    kept, common = drop_ad_unlock_citations_for_product_query(
        query="AD 鎖定",
        ordered_cited_doc_keys=["ad", "vpn"],
        common_doc_keys={"ad", "vpn"},
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert kept == ["ad", "vpn"]
    assert common == {"ad", "vpn"}
