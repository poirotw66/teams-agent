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


def test_negated_topic_fuzzy_demotes_interrupted_crm_title() -> None:
    """Regression: 外網 CRM title must drop for 外網連線設定 even when score leads."""
    primary = SearchResult(
        chunk=DocumentChunk(
            chunk_id="primary",
            title="國金 CRM OTP 綁訂操作",
            content="Google Authenticator 首次登入需使用 OTP Key",
            document_id="primary",
            source_path="sources/primary.md",
        ),
        score=0.72,
        sparse_score=0.72,
        dense_score=0.0,
    )
    support = SearchResult(
        chunk=DocumentChunk(
            chunk_id="support",
            title="外網 CRM 登入連線設定方式",
            content="手機綁定 FortiToken OTP；外網 CRM 權限才能綁定",
            document_id="support",
            source_path="sources/support.md",
        ),
        score=0.95,
        sparse_score=0.95,
        dense_score=0.0,
    )
    for query in (
        "OTP 綁定操作，不是外網連線設定",
        "國金 CRM 的 OTP 要怎麼綁定？不要給我外網 CRM 連線設定",
    ):
        filtered = filter_results_for_generation(
            query=query,
            results=[support, primary],
            document_key=lambda result: result.chunk.document_id or "",
        )
        keys = [result.chunk.document_id for result in filtered]
        assert keys[0] == "primary", query
        assert "support" not in keys, query


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


def test_portal_not_ad_contrast_keeps_employee_portal_over_ad_and_holdings() -> None:
    """Regression:「入口網密碼不是 AD」must keep 並非AD portal doc, not AD/金控."""
    portal = _result(
        "portal",
        "國泰員工入口網、CTeam密碼、國泰e點名",
        "密碼連動為國泰金控網站帳密 (並非AD)，請至忘記密碼",
    )
    ad = _result("ad", "AD 帳號與系統解鎖 FAQ", "AD 帳號鎖定請自助解鎖")
    holdings = _result(
        "hold",
        "金控入口網密碼變更方式",
        "金控入口網畫面設定我的連結後可密碼變更與忘記密碼",
    )
    for query in (
        "公司入口網站密碼不是 AD 對吧？",
        "國泰員工入口密碼是不是 AD？",
    ):
        filtered = filter_results_for_generation(
            query=query,
            results=[ad, holdings, portal],
            document_key=lambda result: result.chunk.document_id or "",
        )
        keys = [result.chunk.document_id for result in filtered]
        assert keys[0] == "portal", query
        assert "ad" not in keys, query


def test_external_crm_connect_not_otp_keeps_connect_doc() -> None:
    """Regression: 外網 CRM 連線設定，不是 OTP 綁定 must drop OTP sibling."""
    connect = _result(
        "crm",
        "外網 CRM 登入連線設定方式",
        "外網 CRM FortiToken 連線設定；手機也可綁定 OTP",
    )
    otp = _result(
        "otp",
        "國金 CRM OTP 綁訂操作",
        "Google Authenticator 首次登入需使用 OTP Key 與 QR Code",
    )
    filtered = filter_results_for_generation(
        query="外網 CRM 連線設定，不是 OTP 綁定",
        results=[otp, connect],
        document_key=lambda result: result.chunk.document_id or "",
    )
    keys = [result.chunk.document_id for result in filtered]
    assert keys[0] == "crm"
    assert "otp" not in keys


def test_same_doc_confirmation_keeps_both_adjacent_product_manuals() -> None:
    """「是不是同一份」must not treat 同一份 as negated and drop a sibling."""
    results = [
        _result(
            "tree",
            "樹精靈AP無法登入",
            "樹精靈無法登入請檢查網路環境與系統連線設定",
        ),
        _result(
            "sonic",
            "超音樹-程式閃退問題",
            "超音樹閃退需安裝新版簽章元件；國泰期貨用戶注意",
        ),
    ]
    filtered = filter_results_for_generation(
        query="樹精靈無法登入跟超音樹閃退是不是同一份？",
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    keys = {result.chunk.document_id for result in filtered}
    assert keys == {"tree", "sonic"}


def test_vpn_password_expiry_packs_forticlient_howto_before_vpn_qa() -> None:
    """Executable Ctrl+Alt+Delete how-to must lead the pack for password-expiry."""
    vpn = SearchResult(
        chunk=DocumentChunk(
            chunk_id="vpn",
            title="VPN常見Q&A問答",
            content="三個月密碼到期，請直接改密碼，不要去金控入口網同步開機密碼(AD)",
            document_id="vpn",
            source_path="sources/vpn.md",
        ),
        score=0.99,
        sparse_score=0.99,
        dense_score=0.0,
    )
    forti = SearchResult(
        chunk=DocumentChunk(
            chunk_id="forti",
            title="登入 FortiClient 出現錯訊",
            content="請插上實體網路線，使用 Ctrl + Alt + Delete 變更開機密碼。",
            document_id="forti",
            source_path="sources/forti.md",
        ),
        score=0.70,
        sparse_score=0.70,
        dense_score=0.0,
    )
    filtered = filter_results_for_generation(
        query="VPN 密碼到期了要怎麼處理？",
        results=[vpn, forti],
        document_key=lambda result: result.chunk.document_id or "",
    )
    assert [result.chunk.document_id for result in filtered[:2]] == ["forti", "vpn"]


def test_iphone_rejects_android_handbook_keeps_ios_primary() -> None:
    """Platform contrast: iPhone query must pack iOS handbook over Android."""
    results = [
        _result(
            "android",
            "行動裝置 Outlook 安裝手冊（Android）",
            "Android Outlook 含 Intune 公司入口網站安裝與登入步驟",
        ),
        _result(
            "ios",
            "行動裝置 Outlook 安裝手冊（iOS）",
            "iOS Outlook 需安裝 Microsoft Authenticator 驗證",
        ),
    ]
    filtered = filter_results_for_generation(
        query="iPhone 收公司信應依哪份 Outlook 手冊，為何不能直接套用 Android 步驟？",
        results=results,
        document_key=lambda result: result.chunk.document_id or "",
    )
    keys = [result.chunk.document_id for result in filtered]
    assert keys[0] == "ios"
    assert "android" not in keys


def test_filter_cross_scenario_iphone_keeps_ios_drops_android() -> None:
    from agent_service.knowledge_pipeline.candidate_policy import (
        filter_cross_scenario_chunks,
    )

    results = [
        _result(
            "android",
            "行動裝置 Outlook 安裝手冊（Android）",
            "Android Outlook 含 Intune",
        ),
        _result(
            "ios",
            "行動裝置 Outlook 安裝手冊（iOS）",
            "iOS Outlook Microsoft Authenticator",
        ),
    ]
    filtered = filter_cross_scenario_chunks(
        "iPhone 收公司信應依哪份 Outlook 手冊，為何不能直接套用 Android 步驟？",
        results,
    )
    keys = [result.chunk.document_id for result in filtered]
    assert keys == ["ios"]
