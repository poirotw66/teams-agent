"""Unit tests for knowledge document-selection policies."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.document_selection import (
    inject_employee_portal_password_evidence,
    inject_enterprise_app_evidence,
    inject_same_doc_discrimination_evidence,
    inject_vpn_password_expiry_howto,
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


def test_inject_employee_portal_password_evidence_appends_companion() -> None:
    portal = _chunk(
        "portal",
        title="國泰員工入口網、CTeam密碼、國泰e點名",
        content="請至國泰員工入口網站-忘記密碼",
        document_id="portal",
    )
    companion = _chunk(
        "holdings",
        title="金控入口網密碼變更方式",
        content="齒輪 > 設定我的連結 > 網站管理",
        document_id="holdings",
    )
    results = [_result(portal, 0.95)]
    boosted = inject_employee_portal_password_evidence(
        "國泰員工入口網忘記密碼",
        results,
        index_chunks=[portal, companion],
        groups={"IT"},
        environment="prod",
    )
    assert [item.chunk.chunk_id for item in boosted] == ["portal", "holdings"]


def test_inject_employee_portal_password_evidence_noop_without_portal_query() -> None:
    companion = _chunk(
        "holdings",
        title="金控入口網密碼變更方式",
        content="設定我的連結",
        document_id="holdings",
    )
    results = [_result(companion, 0.9)]
    boosted = inject_employee_portal_password_evidence(
        "VPN 密碼被鎖",
        results,
        index_chunks=[companion],
        groups={"IT"},
        environment="prod",
    )
    assert [item.chunk.chunk_id for item in boosted] == ["holdings"]


def test_inject_vpn_password_expiry_howto_appends_forticlient_chunk() -> None:
    """Password-expiry how-to must pack FortiClient Ctrl+Alt+Delete companion."""
    vpn = _chunk(
        "vpn",
        title="VPN常見Q&A問答",
        content="三個月密碼到期，請直接改密碼，不要去金控入口網同步開機密碼(AD)",
        document_id="vpn",
    )
    forti = _chunk(
        "forti",
        title="登入 FortiClient 出現錯訊",
        content="三個月密碼到期：請插上實體網路線，使用 Ctrl + Alt + Delete 變更開機密碼。",
        document_id="forti",
    )
    boosted = inject_vpn_password_expiry_howto(
        "VPN 密碼到期了要怎麼處理？",
        [_result(vpn, 0.95)],
        index_chunks=[vpn, forti],
        groups={"IT"},
        environment="prod",
    )
    assert [item.chunk.chunk_id for item in boosted] == ["vpn", "forti"]


def test_vpn_password_expiry_selection_packs_forticlient_howto() -> None:
    """End-to-end select must keep FortiClient how-to beside VPN Q&A."""
    vpn = _chunk(
        "vpn",
        title="VPN常見Q&A問答",
        content="三個月密碼到期，請直接改密碼，不要去金控入口網同步開機密碼(AD)",
        document_id="vpn",
    )
    forti = _chunk(
        "forti",
        title="登入 FortiClient 出現錯訊",
        content="請插上實體網路線，使用 Ctrl + Alt + Delete 變更公司電腦開機密碼。",
        document_id="forti",
    )
    noise = _chunk(
        "ad",
        title="AD 帳號與系統解鎖 FAQ",
        content="AD 解鎖",
        document_id="ad",
    )
    results = [
        SearchResult(
            chunk=vpn,
            score=0.99,
            sparse_score=0.99,
            dense_score=0.0,
            final_rank=1,
            fusion_rank=1,
        ),
        SearchResult(
            chunk=noise,
            score=0.80,
            sparse_score=0.80,
            dense_score=0.0,
            final_rank=2,
            fusion_rank=2,
        ),
        SearchResult(
            chunk=forti,
            score=0.55,
            sparse_score=0.55,
            dense_score=0.0,
            final_rank=8,
            fusion_rank=8,
        ),
    ]
    selected, _ = select_document_chunks(
        "VPN 密碼到期了要怎麼處理？",
        results,
        document_key=lambda result: result.chunk.document_id or result.chunk.chunk_id,
        index_chunks=[vpn, forti, noise],
        top_k=4,
    )
    titles = {item.chunk.title for item in selected}
    assert "VPN常見Q&A問答" in titles
    assert "登入 FortiClient 出現錯訊" in titles


def test_inject_same_doc_discrimination_appends_both_named_manuals() -> None:
    tree = _chunk(
        "tree",
        title="樹精靈AP無法登入",
        content="樹精靈無法登入請檢查網路",
        document_id="tree",
    )
    sonic = _chunk(
        "sonic",
        title="超音樹-程式閃退問題",
        content="超音樹閃退需安裝新版簽章元件；國泰期貨用戶注意",
        document_id="sonic",
    )
    boosted = inject_same_doc_discrimination_evidence(
        "樹精靈無法登入跟超音樹閃退是不是同一份？",
        [_result(tree, 0.95)],
        index_chunks=[tree, sonic],
        groups={"IT"},
        environment="prod",
    )
    assert [item.chunk.chunk_id for item in boosted] == ["tree", "sonic"]


def test_inject_same_doc_discrimination_for_playground_vs_phrasing() -> None:
    """Playground often asks「A vs B」without「是不是同一份」."""
    tree = _chunk(
        "tree",
        title="樹精靈AP無法登入",
        content="樹精靈無法登入請檢查網路",
        document_id="tree",
    )
    sonic = _chunk(
        "sonic",
        title="超音樹-程式閃退問題",
        content="超音樹閃退需安裝新版簽章元件；國泰期貨用戶注意",
        document_id="sonic",
    )
    boosted = inject_same_doc_discrimination_evidence(
        "樹精靈無法登入 vs 超音樹閃退",
        [_result(tree, 0.95)],
        index_chunks=[tree, sonic],
        groups={"IT"},
        environment="prod",
    )
    assert {item.chunk.chunk_id for item in boosted} == {"tree", "sonic"}


def test_same_doc_comparison_keeps_both_named_manuals_despite_distractors() -> None:
    """「是不是同一份」must pack both adjacent product docs, not distractors only."""
    results = [
        SearchResult(
            chunk=_chunk(
                "tree",
                title="樹精靈AP無法登入",
                document_id="tree",
                content="樹精靈無法登入請檢查網路",
            ),
            score=0.95,
            sparse_score=0.95,
            dense_score=0.0,
            final_rank=1,
            fusion_rank=1,
        ),
        SearchResult(
            chunk=_chunk(
                "ad",
                title="AD 帳號與系統解鎖 FAQ",
                document_id="ad",
                content="AD 解鎖",
            ),
            score=0.80,
            sparse_score=0.80,
            dense_score=0.0,
            final_rank=2,
            fusion_rank=2,
        ),
        SearchResult(
            chunk=_chunk(
                "vpn",
                title="VPN常見Q&A問答",
                document_id="vpn",
                content="VPN",
            ),
            score=0.75,
            sparse_score=0.75,
            dense_score=0.0,
            final_rank=3,
            fusion_rank=3,
        ),
        SearchResult(
            chunk=_chunk(
                "sonic",
                title="超音樹-程式閃退問題",
                document_id="sonic",
                content="超音樹閃退需安裝新版簽章元件；國泰期貨用戶注意",
            ),
            score=0.40,
            sparse_score=0.40,
            dense_score=0.0,
            final_rank=4,
            fusion_rank=4,
        ),
    ]
    selected, _ = select_document_chunks(
        "樹精靈無法登入跟超音樹閃退是不是同一份？",
        results,
        document_key=lambda result: result.chunk.document_id or result.chunk.chunk_id,
        index_chunks=[],
        top_k=4,
    )
    doc_ids = [item.chunk.document_id for item in selected]
    assert "tree" in doc_ids
    assert "sonic" in doc_ids
    # Named manuals must pack ahead of high-score distractors.
    assert doc_ids.index("tree") < doc_ids.index("ad")
    assert doc_ids.index("sonic") < doc_ids.index("ad")


def test_same_doc_comparison_recovers_missing_sonic_via_inject() -> None:
    """When retrieval only returns 樹精靈, companion inject must restore 超音樹."""
    tree = _chunk(
        "tree",
        title="樹精靈AP無法登入",
        document_id="tree",
        content="樹精靈無法登入請檢查網路",
    )
    sonic = _chunk(
        "sonic",
        title="超音樹-程式閃退問題",
        document_id="sonic",
        content="超音樹閃退需安裝新版簽章元件；國泰期貨用戶注意",
    )
    noise = _chunk(
        "ad",
        title="AD 帳號與系統解鎖 FAQ",
        document_id="ad",
        content="AD 解鎖",
    )
    query = "樹精靈無法登入跟超音樹閃退是不是同一份？"
    boosted = inject_same_doc_discrimination_evidence(
        query,
        [
            SearchResult(
                chunk=tree,
                score=0.95,
                sparse_score=0.95,
                dense_score=0.0,
                final_rank=1,
                fusion_rank=1,
            ),
            SearchResult(
                chunk=noise,
                score=0.80,
                sparse_score=0.80,
                dense_score=0.0,
                final_rank=2,
                fusion_rank=2,
            ),
        ],
        index_chunks=[tree, sonic, noise],
        groups={"IT"},
        environment="prod",
    )
    selected, _ = select_document_chunks(
        query,
        boosted,
        document_key=lambda result: result.chunk.document_id or result.chunk.chunk_id,
        index_chunks=[tree, sonic, noise],
        top_k=4,
    )
    doc_ids = {item.chunk.document_id for item in selected}
    assert doc_ids >= {"tree", "sonic"}


def test_iphone_platform_constraint_keeps_ios_handbook_not_android() -> None:
    """iPhone + 為何不能套用 Android must keep iOS handbook in the pack."""
    ios_title = "行動裝置 Outlook 安裝手冊（iOS）"
    android_title = "行動裝置 Outlook 安裝手冊（Android）"
    results = [
        SearchResult(
            chunk=_chunk(
                "android",
                title=android_title,
                document_id="android",
                content="Android Outlook 含 Intune 公司入口網站安裝與登入步驟",
            ),
            score=0.95,
            sparse_score=0.95,
            dense_score=0.0,
            final_rank=1,
            fusion_rank=1,
        ),
        SearchResult(
            chunk=_chunk(
                "ios",
                title=ios_title,
                document_id="ios",
                content="iOS Outlook 需安裝 Microsoft Authenticator 驗證",
            ),
            score=0.88,
            sparse_score=0.88,
            dense_score=0.0,
            final_rank=2,
            fusion_rank=2,
        ),
    ]
    query = "iPhone 收公司信應依哪份 Outlook 手冊，為何不能直接套用 Android 步驟？"
    selected, _ = select_document_chunks(
        query,
        results,
        document_key=lambda result: result.chunk.document_id or result.chunk.chunk_id,
        index_chunks=[],
        top_k=4,
    )
    titles = {item.chunk.title for item in selected}
    assert ios_title in titles
    assert android_title not in titles


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
