"""Tests for RAG pipeline improvements (spec §8, §18)."""

from pathlib import Path

import pytest

from agent_service.contracts import (
    Citation,
    GroundedClaim,
    Issue,
    IssueResult,
    RetrievalAttempt,
    RetrievalCandidate,
    RetrievalTrace,
    UserContext,
)
from agent_service.documents import DocumentChunk
from agent_service.extractor import (
    IssueExtractor,
    _has_helpdesk_domain_evidence,
)
from agent_service.knowledge import (
    ANSWER_PROMPT,
    GroundedClaimRepair,
    HybridKnowledgeService,
    RelevanceDecision,
    RewrittenQuery,
    StructuredKnowledgeAnswer,
    _RetrievalState,
)
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import HybridIndex, SearchResult
from agent_service.settings import RagSettings
from agent_service.supervisor import (
    ConversationSupervisor,
    ConversationSupervisorDecision,
)
from agent_service.workflow_issue_processing import _retrieval_probe_is_answerable


def make_settings(tmp_path: Path, **overrides) -> RagSettings:
    defaults = {
        "data_dir": tmp_path,
        "index_path": tmp_path / "index.json",
        "top_k": 2,
        "min_score": 0.05,
        "max_retrieval_rewrites": 1,
        "enable_adaptive_query_tiers": False,
        "rag_reranker_enabled": False,
    }
    defaults.update(overrides)
    return RagSettings(**defaults)


def make_user() -> UserContext:
    return UserContext(
        entraObjectId="user-1",
        displayName="Test User",
        email="user@example.com",
        groups=[],
    )


def test_sanitize_answer_security_replaces_placeholder_urls() -> None:
    raw = (
        "若您的 AD 帳號遭鎖定，請至「AD 自助解鎖專區」：\n"
        "https://xxxxx.pages.dev/Sorry.Only.For.TEST\n"
        "依照指示操作。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "pages.dev" not in sanitized
    assert "Sorry.Only.For.TEST" not in sanitized
    assert "來源僅包含測試連結，目前無法提供正式網址（請洽詢 IT 支援窗口）" in sanitized


def test_sanitize_answer_security_keeps_placeholder_url_from_evidence() -> None:
    from agent_service.knowledge_pipeline.policy_overlay import sanitize_answer_security

    url = "https://xxxxx.pages.dev/Sorry.Only.For.TEST"
    raw = f"若您的 AD 帳號遭鎖定，請至「AD 自助解鎖專區」：\n{url}\n依照指示操作。"
    evidence = f"AD 自助解鎖專區：`{url}`"
    sanitized = sanitize_answer_security(raw, evidence_text=evidence)
    assert url in sanitized
    assert "目前無法提供正式網址" not in sanitized


def test_sanitize_answer_security_redacts_internal_ips_and_unc() -> None:
    raw = (
        "不可使用權限包含公槽資料夾（\\\\10.93.19.22\\shared）及 http://10.93.3.80:8080/crm/ 系統。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "10.93.19.22" not in sanitized
    assert "10.93.3.80" not in sanitized
    assert "內部公槽資料夾" in sanitized
    assert "內部系統伺服器路徑" in sanitized


def test_sanitize_strips_policy_sec_003_outside_its_scope() -> None:
    raw = (
        "報價問題請蒐集商品代碼並寄送至 123@cathaysec.com.tw [S1]。"
        "若不確定資料是否可提交，請先向權責單位確認 [POLICY-SEC-003]。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "[POLICY-SEC-003]" not in sanitized
    assert "[S1]" in sanitized

    # Hedge language like「若涉及安全性設定變更」must not keep SEC-003 alive.
    hedged = (
        "請遵守資料最小化 [POLICY-SEC-001]。"
        "若涉及安全性設定變更，請務必先向權責單位確認 [POLICY-SEC-003]。"
    )
    assert "[POLICY-SEC-003]" not in HybridKnowledgeService._sanitize_answer_security(
        hedged
    )

    scoped = (
        "若需關閉 Proxy，請先向權責單位確認是否受企業政策管制 [POLICY-SEC-003]。"
    )
    assert "[POLICY-SEC-003]" in HybridKnowledgeService._sanitize_answer_security(scoped)


def test_sanitize_strips_misattributed_test_link_policy_sec_001() -> None:
    """QB-004 regression: test-link reminders must not cite POLICY-SEC-001."""
    raw = (
        "針對 GitLab 帳號解鎖，請聯繫專案開發部 張語桐 [S1]。"
        "此外，請注意文件中的測試連結僅為佔位用途，若有相關需求請洽詢上述正式窗口，"
        "切勿使用非正式連結 [POLICY-SEC-001]。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "[POLICY-SEC-001]" not in sanitized
    assert "測試連結" not in sanitized
    assert "張語桐" in sanitized
    assert "[S1]" in sanitized

    valid = "提交畫面或附件前須避免與問題無關的個人及敏感資訊 [POLICY-SEC-001]。"
    assert "[POLICY-SEC-001]" in HybridKnowledgeService._sanitize_answer_security(valid)


def test_sanitize_prunes_uncited_policy_after_stripping_sec_003() -> None:
    """QB-045 regression: stripping SEC-003 must not leave uncited policy prose."""
    raw = (
        "請將「允許在 IE 模式重新載入」設為「允許」[S1]。"
        "關於風險控制，文件未特別說明針對此設定的風險管理措施，"
        "但系統安全政策要求變更安全性設定前須向權責單位確認 [POLICY-SEC-003]。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "[POLICY-SEC-003]" not in sanitized
    assert "向權責單位確認" not in sanitized
    assert "系統安全政策" not in sanitized
    assert "允許在 IE 模式重新載入" in sanitized
    assert "[S1]" in sanitized


def test_sanitize_separates_citation_from_ui_key_brackets() -> None:
    """QB-055 regression: [S1] must not look like another IP-phone key."""
    raw = "使用 IP 話機撥外線：1. 取聽筒。2. 按 [0]。3. 按 [電話號碼] [S1]。"
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "按 [電話號碼]。[S1]" in sanitized
    assert "按 [電話號碼] [S1]" not in sanitized


def test_sanitize_narrows_overbroad_sec002_password_ban() -> None:
    """QB-052 regression: meeting-password fields must not conflict with SEC-002."""
    raw = (
        "請將會議名稱、會議密碼等資料寄送至 123@cathaysec.com.tw [S1]。"
        "嚴禁於郵件中提供任何密碼資訊 [POLICY-SEC-002]。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "任何密碼" not in sanitized
    assert "會議密碼" in sanitized
    assert "登入密碼、憑證密碼與動態驗證碼" in sanitized
    assert "[POLICY-SEC-002]" in sanitized
    assert "[S1]" in sanitized


def test_sanitize_answer_security_appends_proxy_advisory_when_unqualified() -> None:
    raw = "若連線後 Wi-Fi 瞬斷，請至設定將 Proxy 設定全部關閉後重新連線。"
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "Proxy 設定全部關閉" in sanitized
    assert "系統資安政策提醒" in sanitized
    assert "[POLICY-SEC-003]" in sanitized


def test_sanitize_answer_security_appends_advisory_for_cert_bypass_and_ie() -> None:
    # Certificate bypass advice
    raw_cert = "連線若出現憑證問題，可暫時忽略憑證錯誤繼續連線。"
    sanitized_cert = HybridKnowledgeService._sanitize_answer_security(raw_cert)
    assert "系統資安政策提醒" in sanitized_cert
    assert "[POLICY-SEC-003]" in sanitized_cert

    # IE security lowering advice
    raw_ie = "若頁面無法顯示，可至網際網路選項調低安全性等級後重試。"
    sanitized_ie = HybridKnowledgeService._sanitize_answer_security(raw_ie)
    assert "系統資安政策提醒" in sanitized_ie
    assert "[POLICY-SEC-003]" in sanitized_ie


def test_sanitize_answer_security_does_not_duplicate_proxy_advisory() -> None:
    raw = "若需關閉 Proxy，請先向權責單位確認是否受企業政策管制。"
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert sanitized.count("權責單位") == 1
    assert "[POLICY-SEC-003]" in sanitized
    assert "系統資安政策提醒" not in sanitized


def test_sanitize_pairs_sec003_text_and_id_for_invalid_signature_topic() -> None:
    """QB-048: in-scope security reminders must keep text + POLICY-SEC-003 together."""
    raw = (
        "文件畫面顯示「即使簽章無效也允許執行或安裝軟體」僅為大州首次使用設定內容 [S1]。"
        "此外，進行任何安全性設定變更前，請務必向權責單位確認。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "向權責單位確認" in sanitized
    assert "[POLICY-SEC-003]" in sanitized
    assert "[S1]" in sanitized

    # Hedge that only says 洽詢權責單位 (common model wording) must still pair.
    soft = (
        "關於「即使簽章無效也允許執行或安裝軟體」的設定，文件僅記載其位於進階安全性區塊 [S1]。"
        "若您有安裝需求，建議洽詢權責單位確認操作規範。"
    )
    soft_sanitized = HybridKnowledgeService._sanitize_answer_security(soft)
    assert "[POLICY-SEC-003]" in soft_sanitized
    assert "洽詢權責單位確認" in soft_sanitized
    assert soft_sanitized.count("[POLICY-SEC-003]") == 1


def test_sanitize_adds_visual_inventory_caveats_for_invalid_signature() -> None:
    """Visual checkbox inventory must not become enablement advice."""
    raw = (
        "關於「即使簽章無效也允許執行或安裝軟體」，文件記載該項目應為已勾選狀態 [S1]。"
        "安裝前請向權責單位確認。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "應為已勾選" not in sanitized
    assert "畫面顯示為已勾選" in sanitized
    assert "不得據此作為通用排障" in sanitized or "不得" in sanitized
    assert "名稱未詳" in sanitized or "元件名稱" in sanitized
    assert "[POLICY-SEC-003]" in sanitized

def test_repair_structured_answer_aligns_unknowns_and_answerability() -> None:
    # Case 1: PARTIAL without unknowns
    p1 = StructuredKnowledgeAnswer(
        answer="已處理部分問題 [S1]。",
        answerability="PARTIAL",
        claims=[],
        unknowns=[],
    )
    repaired1 = HybridKnowledgeService._repair_structured_answer(p1)
    assert repaired1.answerability == "PARTIAL"
    assert len(repaired1.unknowns) == 1
    assert "權責單位" in repaired1.unknowns[0]

    # Case 2: FULL with unknowns
    p2 = StructuredKnowledgeAnswer(
        answer="完整說明 [S1]。",
        answerability="FULL",
        claims=[],
        unknowns=["需確認後續維護窗口"],
    )
    repaired2 = HybridKnowledgeService._repair_structured_answer(p2)
    assert repaired2.answerability == "PARTIAL"


@pytest.mark.asyncio
async def test_generate_bounded_model_repair_recovers_missing_claims(tmp_path: Path) -> None:
    chunk_1 = DocumentChunk(
        chunk_id="chk-1",
        title="公槽申請手冊",
        source_path="sources/shared.md",
        content="提出共用公槽人員新增或移除申請時，聯繫單應填寫必要資料。",
    )
    chunk_2 = DocumentChunk(
        chunk_id="chk-2",
        title="共用公槽資安手冊",
        source_path="sources/security.md",
        content="提出共用公槽人員新增申請時不可將個人機敏資訊填入聯繫單。",
    )
    index = HybridIndex([chunk_1, chunk_2])

    class RepairingChatModel:
        def with_structured_output(self, schema):
            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    if schema is RelevanceDecision:
                        return RelevanceDecision(relevant=True)
                    if schema is StructuredKnowledgeAnswer:
                        # Initially asymmetric: cites [S1] and [S2] but only generated claim for chk-1
                        return StructuredKnowledgeAnswer(
                            answer="申請共用公槽請填必要資料 [S1]，且不得包含機敏資訊 [S2]。",
                            answerability="FULL",
                            claims=[
                                GroundedClaim(
                                    text="申請共用公槽請填必要資料",
                                    chunkIds=["chk-1"],
                                )
                            ],
                            unknowns=[],
                        )
                    if schema is GroundedClaimRepair:
                        # Model repair correctly extracts grounded claims for both cited chunks
                        return GroundedClaimRepair(
                            claims=[
                                GroundedClaim(
                                    text="申請共用公槽請填必要資料",
                                    chunkIds=["chk-1"],
                                ),
                                GroundedClaim(
                                    text="不得包含機敏資訊",
                                    chunkIds=["chk-2"],
                                ),
                            ]
                        )
                    raise NotImplementedError(f"Unexpected schema {schema}")

            return _StructuredWrapper()

    service = HybridKnowledgeService(
        make_settings(tmp_path, top_k=2),
        index,
        model=RepairingChatModel(),
    )
    result = await service.search(
        "提出共用公槽人員新增申請時應填寫哪些資料",
        make_user(),
    )

    # Bounded model repair succeeds honestly with genuine chunk claims
    assert result.found is True
    assert "[S1]" in result.answer
    assert "[S2]" in result.answer
    assert len(result.sources) == 2
    assert len(result.claims) == 2


@pytest.mark.asyncio
async def test_generate_prunes_hallucinated_citation_instead_of_fail_closed(
    tmp_path: Path,
) -> None:
    chunk_1 = DocumentChunk(
        chunk_id="chk-1",
        title="公槽申請手冊",
        source_path="sources/shared.md",
        content="提出共用公槽人員新增申請時，聯繫單應填寫必要資料。",
    )
    index = HybridIndex([chunk_1])

    class UnrepairableChatModel:
        def with_structured_output(self, schema):
            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    if schema is RelevanceDecision:
                        return RelevanceDecision(relevant=True)
                    if schema is StructuredKnowledgeAnswer:
                        # Hallucinates citation [S2] which does not exist in results
                        return StructuredKnowledgeAnswer(
                            answer="申請共用公槽請填必要資料 [S1] [S2]。",
                            answerability="FULL",
                            claims=[
                                GroundedClaim(
                                    text="申請共用公槽請填必要資料",
                                    chunkIds=["chk-1"],
                                )
                            ],
                            unknowns=[],
                        )
                    if schema is GroundedClaimRepair:
                        return GroundedClaimRepair(claims=[])
                    raise NotImplementedError(f"Unexpected schema {schema}")

            return _StructuredWrapper()

    service = HybridKnowledgeService(
        make_settings(tmp_path, top_k=2),
        index,
        model=UnrepairableChatModel(),
    )
    result = await service.search(
        "提出共用公槽申請",
        make_user(),
    )
    # Keep grounded [S1] content; drop unresolved hallucinated [S2] without miss.
    assert result.found is True
    assert "[S1]" in result.answer
    assert "[S2]" not in result.answer
    assert len(result.sources) == 1
    assert result.sources[0].chunkId == "chk-1"


def test_supervisor_constrains_non_it_when_error_code_present() -> None:
    message = "使用者回報錯誤 12029，但裝置版本不明。應先採取什麼原則？"
    decision = ConversationSupervisorDecision(intent="NON_IT", confidence=0.9)
    constrained = ConversationSupervisor._constrain_model_decision(decision, message=message)
    assert constrained.intent == "IT_SUPPORT"


def test_supervisor_requires_composite_signals_for_ambiguous_terms() -> None:
    # Standalone generic terms should NOT trigger IT_SUPPORT
    assert _has_helpdesk_domain_evidence("這份文件的處置原則是什麼？") is False
    assert _has_helpdesk_domain_evidence("外洩敏感資訊請參考公司規範") is False
    assert _has_helpdesk_domain_evidence("此行政事項的管控政策由各部門主管自訂") is False
    assert _has_helpdesk_domain_evidence("會議室借用的操作順序說明") is False

    # Composite signals SHOULD trigger IT_SUPPORT
    assert _has_helpdesk_domain_evidence("總公司系統問題處置原則是什麼？") is True
    assert _has_helpdesk_domain_evidence("行動裝置管控政策說明") is True
    assert _has_helpdesk_domain_evidence("手冊中來源能支持哪些操作方式？") is True
    assert _has_helpdesk_domain_evidence("VPN 系統處置原則說明") is True


def test_retrieval_probe_answerability_conjunctive_requirements() -> None:
    test_issue = Issue(
        id=1,
        description="詢問通話中直接轉接至另一分機的操作方式",
        isIT=True,
        readiness="NEED_MORE_INFO",
        route="KNOWLEDGE",
        missingInfo=["請提供話機型號"],
    )
    citation = Citation(
        title="總公司IP話機操作",
        chunkId="chk-ip-1",
        documentId="doc-ip-1",
        canonicalSourceId="doc-ip-1",
    )
    trace = RetrievalTrace(
        rawUserUtterance="通話中要直接轉接至另一分機，應如何操作？",
        resolvedIssueQuery="詢問通話中直接轉接至另一分機的操作方式",
        searchQuery="詢問通話中直接轉接至另一分機的操作方式",
        facetQueries=[],
        selectedBackend="HYBRID",
        actualBackend="HYBRID",
        attempts=[
            RetrievalAttempt(
                searchQuery="詢問通話中直接轉接至另一分機的操作方式",
                candidates=[
                    RetrievalCandidate(
                        rank=1,
                        chunkId="chk-ip-1",
                        documentId="doc-ip-1",
                        canonicalSourceId="doc-ip-1",
                        title="總公司IP話機操作",
                        score=0.858,
                        scoreOrigin="HYBRID",
                        selectedForContext=True,
                    )
                ],
            )
        ],
        selectedChunkIds=["chk-ip-1"],
        answerability="FULL",
        claims=[GroundedClaim(text="按下話機轉接鍵", chunkIds=["chk-ip-1"])],
        unknowns=[],
        fallbackPath="GENERATED_ANSWER",
    )

    # 1. Valid probe meeting all conjunctive requirements
    valid_probe = IssueResult(
        issueId=1,
        resultType="KNOWLEDGE_ANSWERED",
        answer="請按下話機轉接鍵 [S1]。",
        sources=[citation],
        answerability="FULL",
        claims=[GroundedClaim(text="按下話機轉接鍵", chunkIds=["chk-ip-1"])],
        unknowns=[],
        retrievalTrace=trace,
    )
    assert _retrieval_probe_is_answerable(test_issue, valid_probe) is True

    # 2. Reject if claims are empty
    no_claims_probe = valid_probe.model_copy(update={"claims": []})
    assert _retrieval_probe_is_answerable(test_issue, no_claims_probe) is False

    # 3. Accept valid PARTIAL probe with grounded claims
    partial_probe = valid_probe.model_copy(
        update={
            "answerability": "PARTIAL",
            "unknowns": ["型號未明以權責單位規範為準"],
        }
    )
    assert _retrieval_probe_is_answerable(test_issue, partial_probe) is True

    # 4. Reject if answerability is NONE
    none_probe = valid_probe.model_copy(update={"answerability": "NONE"})
    assert _retrieval_probe_is_answerable(test_issue, none_probe) is False

    # 5. Reject if answer indicates conditional branching based on missing info
    branching_probe = valid_probe.model_copy(
        update={"answer": "請先確認您的話機型號，若為不同機型步驟不同 [S1]。"}
    )
    assert _retrieval_probe_is_answerable(test_issue, branching_probe) is False

    # 6. Reject if answer contains cross-scenario conflicts
    conflicting_probe = valid_probe.model_copy(
        update={"answer": "請依 FAQ-001 填寫資訊，但亦須注意 FAQ-002 之交易密碼限制 [S1]。"}
    )
    assert _retrieval_probe_is_answerable(test_issue, conflicting_probe) is False


def test_cross_scenario_chunk_filtering() -> None:
    quote_chunk = DocumentChunk(
        chunk_id="chk-quote",
        title="外部客戶線上問題",
        source_path="sources/外部客戶線上問題.md",
        section="FAQ-004｜報價問題如何回報？",
        content="報價功能發生五檔或行情異常時之回報指引。",
    )
    trade_chunk = DocumentChunk(
        chunk_id="chk-trade",
        title="外部客戶線上問題",
        source_path="sources/外部客戶線上問題.md",
        section="FAQ-002｜交易問題如何回報？",
        content="交易或下單異常時之回報指引，請勿提供交易密碼。",
    )
    results = [
        SearchResult(chunk=quote_chunk, score=0.9, sparse_score=0.9),
        SearchResult(chunk=trade_chunk, score=0.85, sparse_score=0.85),
    ]

    # Query about quote should drop the trade chunk
    filtered_quote = HybridKnowledgeService._filter_cross_scenario_chunks(
        "外部客戶報價五檔資訊異常回報指引", results
    )
    assert len(filtered_quote) == 1
    assert filtered_quote[0].chunk.chunk_id == "chk-quote"

    # Query about trade should drop the quote chunk
    filtered_trade = HybridKnowledgeService._filter_cross_scenario_chunks(
        "客戶交易下單失敗如何回報？", results
    )
    assert len(filtered_trade) == 1
    assert filtered_trade[0].chunk.chunk_id == "chk-trade"


def test_extractor_preserves_qualifiers_from_raw_utterance(tmp_path: Path) -> None:
    extractor = IssueExtractor(make_settings(tmp_path), None)
    raw_issues = [
        Issue(
            id=1,
            description="關閉 Proxy 設定方式",
            isIT=True,
            readiness="READY",
            missingInfo=[],
            route="KNOWLEDGE",
            faqKey=None,
        )
    ]
    # QB-094: raw utterance has "未確認政策"
    coerced, _ = extractor._postprocess(
        raw_issues,
        faq_keys=[],
        raw_utterance="若未確認政策，可否關閉 Proxy？",
    )
    assert "未確認政策" in coerced[0].description
    assert "可否" in coerced[0].description


@pytest.mark.asyncio
async def test_rewrite_preserves_multiple_constraint_markers(tmp_path: Path) -> None:
    class DroppedConstraintsChatModel:
        def with_structured_output(self, schema):
            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    # Model mistakenly dropped both "未確認政策" and "為何不能"
                    return RewrittenQuery(query="FortiClient Proxy 設定")

            return _StructuredWrapper()

    service = HybridKnowledgeService(
        make_settings(tmp_path),
        HybridIndex([]),
        model=DroppedConstraintsChatModel(),
    )
    initial_state = _RetrievalState(
        raw_user_utterance="若未確認政策，為何不能關閉 Proxy？",
        resolved_issue_query="詢問未確認政策為何不能關閉 Proxy",
        search_query="詢問未確認政策為何不能關閉 Proxy",
        facet_queries=[],
    )
    new_state = await service._rewrite(
        initial_state,
        LlmCallCounter(),
    )
    # Both constraint markers are preserved
    assert "未確認政策" in new_state.search_query
    assert "為何不能" in new_state.search_query


@pytest.mark.asyncio
async def test_skip_relevance_llm_on_high_confidence_bypasses_model_call(tmp_path: Path) -> None:
    chunk = DocumentChunk(
        chunk_id="chk-ad",
        title="AD 帳號與系統解鎖 FAQ",
        source_path="sources/ad.md",
        content="AD 帳號遭鎖定時，請至 AD 自助解鎖專區進行解鎖。",
    )
    index = HybridIndex([chunk])

    class CounterTrackingModel:
        def __init__(self):
            self.calls: list[str] = []

        def with_structured_output(self, schema):
            outer = self

            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    outer.calls.append(schema.__name__)
                    if schema is RelevanceDecision:
                        return RelevanceDecision(relevant=True)
                    if schema is StructuredKnowledgeAnswer:
                        return StructuredKnowledgeAnswer(
                            answer="AD 帳號遭鎖定請至自助解鎖專區 [S1]。",
                            answerability="FULL",
                            claims=[
                                GroundedClaim(
                                    text="AD 帳號遭鎖定請至自助解鎖專區",
                                    chunkIds=["chk-ad"],
                                )
                            ],
                            unknowns=[],
                        )
                    raise NotImplementedError(schema)

            return _StructuredWrapper()

    tracking_model = CounterTrackingModel()
    settings = make_settings(tmp_path, skip_relevance_llm_on_high_confidence=True)
    service = HybridKnowledgeService(settings, index, model=tracking_model)

    result = await service.search("AD 帳號鎖定如何自助解鎖", make_user())

    assert result.found is True
    # RelevanceDecision was bypassed because of high confidence hit
    assert "RelevanceDecision" not in tracking_model.calls
    assert "StructuredKnowledgeAnswer" in tracking_model.calls
    assert len(tracking_model.calls) == 1
    assert result.retrievalTrace.attempts[0].decision == "HIGH_CONFIDENCE_PASS"


@pytest.mark.asyncio
async def test_unbacked_citation_pruned_without_discarding_answer(tmp_path: Path) -> None:
    chunk_1 = DocumentChunk(
        chunk_id="chk-1",
        title="公槽申請手冊",
        source_path="sources/shared.md",
        content="提出共用公槽人員新增或移除申請時，聯繫單應填寫必要資料。",
    )
    chunk_2 = DocumentChunk(
        chunk_id="chk-2",
        title="共用公槽資安手冊",
        source_path="sources/security.md",
        content="提出共用公槽人員新增申請時不可將個人機敏資訊填入聯繫單。",
    )
    index = HybridIndex([chunk_1, chunk_2])

    class UnrepairableModel:
        def with_structured_output(self, schema):
            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    if schema is RelevanceDecision:
                        return RelevanceDecision(relevant=True)
                    if schema is StructuredKnowledgeAnswer:
                        # Model cites [S1] and [S2], but only generates claim for chk-1
                        return StructuredKnowledgeAnswer(
                            answer="申請共用公槽請填必要資料 [S1]，另外參考規範 [S2]。",
                            answerability="FULL",
                            claims=[
                                GroundedClaim(
                                    text="申請共用公槽請填必要資料",
                                    chunkIds=["chk-1"],
                                )
                            ],
                            unknowns=[],
                        )
                    if schema is GroundedClaimRepair:
                        # Repair cannot ground S2, returns only valid claim for chk-1
                        return GroundedClaimRepair(
                            claims=[
                                GroundedClaim(
                                    text="申請共用公槽請填必要資料",
                                    chunkIds=["chk-1"],
                                )
                            ]
                        )
                    raise NotImplementedError(schema)

            return _StructuredWrapper()

    service = HybridKnowledgeService(
        make_settings(tmp_path, top_k=2),
        index,
        model=UnrepairableModel(),
    )
    result = await service.search(
        "提出共用公槽人員新增申請時應填寫哪些資料",
        make_user(),
    )

    # Deterministic pruning removes unbacked [S2] and keeps [S1] answer instead of UNGROUNDED_ANSWER miss
    assert result.found is True
    assert "[S1]" in result.answer
    assert "[S2]" not in result.answer
    assert len(result.sources) == 1
    assert result.sources[0].chunkId == "chk-1"


def test_domain_isolation_filters_external_faq_and_cross_product() -> None:
    it_chunk = DocumentChunk(
        chunk_id="ad-1",
        title="AD 帳號與系統解鎖 FAQ",
        source_path="sources/ad.md",
        content="AD 帳號鎖定請使用自助解鎖專區。",
    )
    external_chunk = DocumentChunk(
        chunk_id="ext-1",
        title="外部客戶線上問題",
        source_path="sources/external.md",
        content="外部客戶線上問題請寄送至 123@cathaysec.com.tw 處理。",
    )
    phone_chunk = DocumentChunk(
        chunk_id="phone-1",
        title="總公司IP話機操作",
        source_path="sources/phone.md",
        content="IP話機轉接請按 Transfer 按鍵。",
    )
    outlook_chunk = DocumentChunk(
        chunk_id="outlook-1",
        title="行動裝置 Outlook 安裝手冊（iOS）",
        source_path="sources/outlook.md",
        content="iOS Outlook 首次設定步驟包含 Microsoft Authenticator 驗證。",
    )

    # 1. Internal IT query excludes external customer support
    it_results = [
        SearchResult(chunk=it_chunk, score=0.9, sparse_score=0.9, dense_score=0.0),
        SearchResult(chunk=external_chunk, score=0.8, sparse_score=0.8, dense_score=0.0),
    ]
    filtered_it = HybridKnowledgeService._filter_cross_scenario_chunks(
        "AD 帳號明確遭鎖定時，使用者應如何處理？",
        it_results,
    )
    assert len(filtered_it) == 1
    assert filtered_it[0].chunk.chunk_id == "ad-1"

    # 2. Outlook query excludes Cisco IP phone
    outlook_results = [
        SearchResult(chunk=outlook_chunk, score=0.85, sparse_score=0.85, dense_score=0.0),
        SearchResult(chunk=phone_chunk, score=0.82, sparse_score=0.82, dense_score=0.0),
    ]
    filtered_outlook = HybridKnowledgeService._filter_cross_scenario_chunks(
        "iOS Outlook 首次設定的視覺順序為何？",
        outlook_results,
    )
    assert len(filtered_outlook) == 1
    assert filtered_outlook[0].chunk.chunk_id == "outlook-1"


def test_procedure_expansion_orders_numbered_sections(tmp_path: Path) -> None:
    chunks = [
        DocumentChunk(
            chunk_id="sec-5",
            title="行動裝置 Outlook 安裝手冊（iOS）",
            source_path="sources/ios_outlook.md",
            document_id="doc-ios",
            section="5. Outlook App 設定",
            content="5. Outlook App 設定步驟...",
        ),
        DocumentChunk(
            chunk_id="sec-1",
            title="行動裝置 Outlook 安裝手冊（iOS）",
            source_path="sources/ios_outlook.md",
            document_id="doc-ios",
            section="1. 驗證程式下載、設定驗證器",
            content="1. 驗證程式下載步驟...",
        ),
        DocumentChunk(
            chunk_id="sec-2",
            title="行動裝置 Outlook 安裝手冊（iOS）",
            source_path="sources/ios_outlook.md",
            document_id="doc-ios",
            section="2. 驗證程式綁定手機 App",
            content="2. 驗證程式綁定步驟...",
        ),
    ]
    index = HybridIndex(chunks)
    service = HybridKnowledgeService(make_settings(tmp_path), index)
    results = [
        SearchResult(chunk=chunks[0], score=0.9, sparse_score=0.9, dense_score=0.0),
    ]
    selected, displaced = service._select_document_chunks(
        "iOS Outlook 首次設定的視覺順序為何？", results
    )
    assert displaced is False
    # Selected chunks should expand all numbered sections and order them naturally (1, 2, 5)
    sections = [r.chunk.section for r in selected]
    assert sections == [
        "1. 驗證程式下載、設定驗證器",
        "2. 驗證程式綁定手機 App",
        "5. Outlook App 設定",
    ]


def test_sentence_level_pruning_removes_unbacked_clause() -> None:
    text = "申請共用公槽請填必要資料 [S1]，另外參考規範 [S2]。"
    common_keys = {"doc-1"}

    def _resolve(val: int) -> str | None:
        return "doc-1" if val == 1 else "doc-2"

    cleaned = HybridKnowledgeService._prune_unbacked_sentences_and_citations(
        text,
        common_keys,
        _resolve,
    )
    assert "[S1]" in cleaned
    assert "[S2]" not in cleaned
    assert "另外參考規範" not in cleaned
    assert "申請共用公槽請填必要資料 [S1]。" in cleaned


def test_normalize_composite_citation_markers_expands_lists() -> None:
    from agent_service.knowledge import normalize_composite_citation_markers

    text = "步驟一 [S2, S3]。步驟二 [S1，S2]。"
    normalized = normalize_composite_citation_markers(text)
    assert normalized == "步驟一 [S2][S3]。步驟二 [S1][S2]。"


def test_remap_claim_marker_ids_to_chunk_ids() -> None:
    from agent_service.knowledge import remap_claim_marker_ids_to_chunk_ids

    claims = [
        GroundedClaim(text="白名單僅含 CRM 與 OA", chunkIds=["S1", "POLICY-SEC-002"]),
        GroundedClaim(text="公槽不可使用", chunkIds=["s1"]),
        GroundedClaim(text="完全無關的主張", chunkIds=["S1"]),
    ]
    remapped = remap_claim_marker_ids_to_chunk_ids(
        claims,
        marker_to_chunk_ids={
            "S1": ["chk-allow", "chk-deny"],
            "s1": ["chk-allow", "chk-deny"],
        },
        chunk_content_by_id={
            "chk-allow": "VPN 可使用權限白名單包含 CRM 與 OA。",
            "chk-deny": "VPN 不可使用公槽資料夾。",
        },
    )
    assert remapped[0].chunkIds == ["chk-allow", "POLICY-SEC-002"]
    assert remapped[1].chunkIds == ["chk-deny"]
    assert all(claim.text != "完全無關的主張" for claim in remapped)


def test_answer_indicates_insufficient_information_covers_common_gap_phrasing() -> None:
    from agent_service.knowledge_pipeline import answer_indicates_insufficient_information

    assert answer_indicates_insufficient_information(
        "目前知識庫中並未記載關於 VPN 存取範圍的相關規定。"
    )
    assert answer_indicates_insufficient_information(
        "目前無法從企業知識庫找到可確認的答案。"
    )
    assert answer_indicates_insufficient_information("知識庫未提供該權限清單。")
    assert not answer_indicates_insufficient_information(
        "VPN 連線後僅可存取白名單系統 [S1]。"
    )


@pytest.mark.asyncio
async def test_false_none_retries_even_without_legacy_gap_markers(tmp_path: Path) -> None:
    """NONE with empty claims must retry once even when phrasing is 「並未記載」."""
    chunk = DocumentChunk(
        chunk_id="cs-vpn",
        title="分公司CS團隊VPN連線可使用權限列表",
        source_path="sources/cs-vpn.md",
        content=(
            "通路事業處 CS 人員 VPN 連線可使用權限包含經紀 CRM 與 OA；"
            "不可使用公槽資料夾。因此 VPN 連線不代表可存取所有內部系統。"
        ),
    )
    index = HybridIndex([chunk])
    calls = {"generate": 0}

    class FalseNoneThenGroundedModel:
        def with_structured_output(self, schema):
            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    if schema is RelevanceDecision:
                        return RelevanceDecision(relevant=True)
                    if schema is StructuredKnowledgeAnswer:
                        calls["generate"] += 1
                        if calls["generate"] == 1:
                            return StructuredKnowledgeAnswer(
                                answer=(
                                    "目前知識庫中並未記載關於透過 VPN 連線後是否代表"
                                    "可存取所有內部系統的相關規定。"
                                ),
                                answerability="NONE",
                                claims=[],
                                unknowns=["VPN連線後的系統存取權限範圍"],
                            )
                        return StructuredKnowledgeAnswer(
                            answer=(
                                "否。CS 人員 VPN 僅可使用白名單系統（如 CRM、OA），"
                                "不可使用公槽，因此不代表可存取所有內部系統 [S1]。"
                            ),
                            answerability="FULL",
                            claims=[
                                GroundedClaim(
                                    text="CS VPN 僅可使用白名單系統，不可使用公槽",
                                    chunkIds=["cs-vpn"],
                                )
                            ],
                            unknowns=[],
                        )
                    if schema is GroundedClaimRepair:
                        return GroundedClaimRepair(claims=[])
                    raise NotImplementedError(schema)

            return _StructuredWrapper()

    settings = make_settings(tmp_path, top_k=3, skip_relevance_llm_on_high_confidence=True)
    service = HybridKnowledgeService(
        settings, index, model=FalseNoneThenGroundedModel()
    )
    result = await service.search(
        "特定角色透過 VPN 連線後，是否代表可存取所有內部系統？",
        make_user(),
    )

    assert calls["generate"] == 2
    assert result.found is True
    assert result.terminalReason != "UNGROUNDED_ANSWER"
    assert "不代表" in result.answer or "否" in result.answer
    assert result.sources


def test_qb052_webex_not_filtered_by_audience_heuristic() -> None:
    webex_chunk = DocumentChunk(
        chunk_id="webex-1",
        title="Webex會議借用-可錄影",
        source_path="sources/webex.md",
        content="同仁申請可錄影會議請寄至 123@cathaysec.com.tw 申請借用。",
    )
    external_chunk = DocumentChunk(
        chunk_id="ext-1",
        title="外部客戶線上問題",
        source_path="sources/external.md",
        content="外部客戶線上問題請寄送至 123@cathaysec.com.tw 處理。",
    )
    results = [
        SearchResult(chunk=webex_chunk, score=0.89, sparse_score=0.89, dense_score=0.0),
        SearchResult(chunk=external_chunk, score=0.80, sparse_score=0.80, dense_score=0.0),
    ]
    filtered = HybridKnowledgeService._filter_cross_scenario_chunks(
        "同仁需要可錄影的 Webex 會議，已備妥必要欄位。接下來應如何完成申請？",
        results,
    )
    assert any(r.chunk.chunk_id == "webex-1" for r in filtered)


def test_qb061_xq_query_with_customer_complaint_retains_xq_doc() -> None:
    xq_chunk = DocumentChunk(
        chunk_id="xq-1",
        title="XQ問題",
        source_path="sources/xq.md",
        content="客戶反映 XQ 無法下單時，第一步請先交叉測試下單連線。",
    )
    external_chunk = DocumentChunk(
        chunk_id="ext-1",
        title="外部客戶線上問題",
        source_path="sources/external.md",
        content="外部客戶線上問題回報流程說明。",
    )
    results = [
        SearchResult(chunk=xq_chunk, score=0.85, sparse_score=0.85, dense_score=0.0),
        SearchResult(chunk=external_chunk, score=0.82, sparse_score=0.82, dense_score=0.0),
    ]
    filtered = HybridKnowledgeService._filter_cross_scenario_chunks(
        "客戶反映 XQ 無法下單時，支援人員應如何進行第一步交叉測試？",
        results,
    )
    assert any(r.chunk.chunk_id == "xq-1" for r in filtered)


def test_filter_displaced_top1_prohibits_high_confidence_bypass(tmp_path: Path) -> None:
    chunk_1 = DocumentChunk(
        chunk_id="chk-1",
        title="一般系統手冊",
        source_path="sources/general.md",
        content="一般系統操作指南。",
    )
    index = HybridIndex([chunk_1])
    service = HybridKnowledgeService(make_settings(tmp_path), index)

    res = SearchResult(chunk=chunk_1, score=0.85, sparse_score=0.85, dense_score=0.0)
    # When filter_displaced_top1 is True, it must NOT take HIGH_CONFIDENCE_PASS
    state_displaced = _RetrievalState(
        raw_user_utterance="test",
        resolved_issue_query="test",
        search_query="test",
        results=[res],
        filter_displaced_top1=True,
    )
    decision, is_det = service._evaluate_retrieval_confidence(state_displaced)
    assert decision == "LLM_RELEVANCE"
    assert is_det is False


def test_qb085_answer_prompt_rules_contain_global_security_baseline() -> None:
    assert "全域資料最小化原則" in ANSWER_PROMPT
    assert "絕對機敏資訊禁令" in ANSWER_PROMPT
    assert "全域最高性" in ANSWER_PROMPT
    assert "[POLICY-SEC-001]" in ANSWER_PROMPT
    assert "[POLICY-SEC-002]" in ANSWER_PROMPT
    assert "[POLICY-SEC-003]" in ANSWER_PROMPT
    assert "該來源沒有規定" in ANSWER_PROMPT


def test_answer_prompt_security_rules_align_with_policy_bodies() -> None:
    from agent_service.security_policies import ANSWER_PROMPT_SECURITY_RULES

    assert "POLICY-SEC-003" in ANSWER_PROMPT_SECURITY_RULES
    assert "Proxy" in ANSWER_PROMPT_SECURITY_RULES or "憑證" in ANSWER_PROMPT_SECURITY_RULES
    # Must not reintroduce the free-floating submit-confirmation rule that
    # caused models to mis-attribute data-submit guidance to POLICY-SEC-003.
    assert "不確定時確認原則" not in ANSWER_PROMPT_SECURITY_RULES
    assert "嚴禁把「資料能否提交」「正式網址查詢」「一般通報流程」標成 [POLICY-SEC-003]。" in (
        ANSWER_PROMPT_SECURITY_RULES
    )
    assert "嚴禁把「測試連結／佔位網址／非正式連結」標成 [POLICY-SEC-001]" in (
        ANSWER_PROMPT_SECURITY_RULES
    )
    assert "此提醒不是安全政策，嚴禁標成 [POLICY-SEC-001]" in ANSWER_PROMPT_SECURITY_RULES
    assert "會議密碼" in ANSWER_PROMPT_SECURITY_RULES
    assert "不得寫成「任何密碼／所有密碼」" in ANSWER_PROMPT_SECURITY_RULES


def test_unknown_policy_markers_do_not_crash_advisories() -> None:
    from agent_service.security_policies import (
        advisories_from_text,
        strip_unknown_policy_markers,
    )

    text = "請遵守資料最小化 [POLICY-SEC-001]，並參考未知規則 [POLICY-SEC-999]。"
    advisories = advisories_from_text(text)
    assert [a.policyIds for a in advisories] == [["POLICY-SEC-001"]]
    stripped = strip_unknown_policy_markers(text)
    assert "[POLICY-SEC-001]" in stripped
    assert "[POLICY-SEC-999]" not in stripped


def test_uncited_security_policy_leak_is_pruned() -> None:
    text = (
        "申請共用公槽請填必要資料 [S1]。\n"
        "另請注意資料最小化，勿提交無關敏感資訊。"
    )
    common_keys = {"doc-1"}

    def _resolve(val: int) -> str | None:
        return "doc-1" if val == 1 else None

    cleaned = HybridKnowledgeService._prune_unbacked_sentences_and_citations(
        text,
        common_keys,
        _resolve,
    )
    assert "[S1]" in cleaned
    assert "資料最小化" not in cleaned


def test_same_line_uncited_policy_clause_is_pruned() -> None:
    text = "申請共用公槽請填必要資料 [S1]，另請注意資料最小化勿提交無關敏感資訊。"
    cleaned = HybridKnowledgeService._prune_uncited_material_sentences(text)
    assert "[S1]" in cleaned
    assert "申請共用公槽請填必要資料" in cleaned
    assert "資料最小化" not in cleaned


def test_policy_boilerplate_misattributed_to_knowledge_citation_is_pruned() -> None:
    """Baseline #06 FAIL pattern: policy hedges falsely tagged as [S#]."""
    text = (
        "請先重啟數據機，再改用手機網路分享測試 [S1]。"
        "關於後續調整 TLS 或 Proxy 設定，變更前需先向權責單位或資訊部門確認適用性，"
        "切勿擅自變更 [S1]。"
        "調整時請取消勾選 SSL 3.0 並勾選 TLS 1.2 [S1]。"
    )
    cleaned = HybridKnowledgeService._prune_uncited_material_sentences(text)
    assert "重啟數據機" in cleaned
    assert "TLS 1.2" in cleaned
    assert "資訊部門確認" not in cleaned
    assert "切勿擅自變更" not in cleaned


def test_rule10_data_minimization_misattributed_as_source_limit_is_pruned() -> None:
    text = (
        "問題類型應歸類為「報價」[S1]。"
        "關於資料保護的限制，文件僅規範全域資安與資料最小化原則，"
        "嚴禁提供登入密碼等機敏資訊 [Rule 10]。"
    )
    cleaned = HybridKnowledgeService._prune_uncited_material_sentences(text)
    assert "報價" in cleaned
    assert "資料最小化" not in cleaned
    assert "登入密碼" not in cleaned
    assert "Rule 10" not in cleaned


def test_legitimate_policy_sec_marker_is_preserved() -> None:
    text = (
        "請將 Proxy 伺服器設為不勾選 [S1]。"
        "變更前請向權責單位確認 [POLICY-SEC-003]。"
    )
    cleaned = HybridKnowledgeService._prune_uncited_material_sentences(text)
    assert "Proxy" in cleaned
    assert "[POLICY-SEC-003]" in cleaned
    assert "向權責單位確認" in cleaned


def test_policy_advisory_line_body_is_preserved() -> None:
    text = (
        "可關閉 Proxy 後重新連線 [S1]。\n"
        "> ⚠️ **系統資安政策提醒** [POLICY-SEC-003]：此操作涉及安全性、Proxy 或憑證設定變更。"
        "若該裝置是否受企業政策管轄狀態未明，執行前應先向權責單位或 IT 支援窗口確認，"
        "切勿擅自變更或停用安全防護設定。"
    )
    cleaned = HybridKnowledgeService._prune_uncited_material_sentences(text)
    assert "關閉 Proxy" in cleaned
    assert "[POLICY-SEC-003]" in cleaned
    assert "向權責單位或 IT 支援窗口確認" in cleaned
    assert "切勿擅自變更" in cleaned


def test_error_branch_coverage_helpers() -> None:
    from agent_service.knowledge_pipeline import (
        answer_covers_error_branches,
        error_branch_codes_in_text,
    )

    context = "### Permission denied (-455)\n...\n### Unable (-14)\n...\n### Session (-20199)\n"
    codes = error_branch_codes_in_text(context)
    assert codes == ["-455", "-14", "-20199"]
    assert not answer_covers_error_branches(
        "請先確認網路與軟體狀態後聯絡服務台。", codes
    )
    assert answer_covers_error_branches(
        "(-455) 查網路；(-14) 更新版本；(-20199) 重登。", codes
    )


def test_ux_audit_chunks_are_filtered_from_context() -> None:
    production = DocumentChunk(
        chunk_id="forti-1",
        title="登入 FortiClient 出現錯訊",
        source_path="sources/forti.md",
        content="Permission denied (-455) 請確認網路。",
    )
    audit = DocumentChunk(
        chunk_id="audit-1",
        title="[UX-AUDIT] VPN 連線測試文件",
        source_path="sources/ux-audit.md",
        content="通用排查：確認網路與軟體狀態。",
    )
    filtered = HybridKnowledgeService._filter_cross_scenario_chunks(
        "收到 FortiClient 錯誤時如何分流？",
        [
            SearchResult(chunk=production, score=0.9, sparse_score=0.9, dense_score=0.0),
            SearchResult(chunk=audit, score=0.85, sparse_score=0.85, dense_score=0.0),
        ],
    )
    assert [item.chunk.chunk_id for item in filtered] == ["forti-1"]


def test_enterprise_app_query_prefers_device_management_doc() -> None:
    portal = DocumentChunk(
        chunk_id="portal-1",
        title="國泰員工入口網、CTeam密碼、國泰e點名",
        source_path="sources/portal.md",
        content="安裝完成請務必至手機一般 > VPN與裝置管理 > 企業級APP內將CATHAY LIFE加入驗證。",
    )
    external = DocumentChunk(
        chunk_id="ext-1",
        title="外部客戶線上問題",
        source_path="sources/external.md",
        content="請寄送至 123@cathaysec.com.tw。",
    )
    ad = DocumentChunk(
        chunk_id="ad-1",
        title="AD 帳號與系統解鎖 FAQ",
        source_path="sources/ad.md",
        content="帳號鎖定請至 AD 自助解鎖專區。",
    )
    filtered = HybridKnowledgeService._filter_cross_scenario_chunks(
        "iOS 上安裝來源所述的企業 App 後仍無法使用，應檢查什麼？",
        [
            SearchResult(chunk=ad, score=0.92, sparse_score=0.92, dense_score=0.0),
            SearchResult(chunk=external, score=0.90, sparse_score=0.90, dense_score=0.0),
            SearchResult(chunk=portal, score=0.80, sparse_score=0.80, dense_score=0.0),
        ],
    )
    assert filtered[0].chunk.chunk_id == "portal-1"
    assert all(item.chunk.chunk_id != "ext-1" for item in filtered)


def test_enterprise_app_inject_does_not_reintroduce_acl_excluded_chunks(
    tmp_path: Path,
) -> None:
    """Regression: post-search boost must not bypass Hybrid ACL filtering."""
    public_ad = DocumentChunk(
        chunk_id="ad-1",
        title="AD 帳號與系統解鎖 FAQ",
        source_path="sources/ad.md",
        content="帳號鎖定請至 AD 自助解鎖專區。",
        allowed_groups=[],
    )
    restricted_portal = DocumentChunk(
        chunk_id="portal-restricted",
        title="國泰員工入口網、CTeam密碼、國泰e點名",
        source_path="sources/portal-restricted.md",
        content=(
            "安裝完成請務必至手機一般 > VPN與裝置管理 > "
            "企業級APP內將CATHAY LIFE加入驗證。"
        ),
        allowed_groups=["IT"],
    )
    index = HybridIndex([public_ad, restricted_portal])
    service = HybridKnowledgeService(make_settings(tmp_path), index, model=None)
    query = "iOS 上安裝來源所述的企業 App 後仍無法使用，應檢查什麼？"
    acl_filtered = [
        SearchResult(chunk=public_ad, score=0.8, sparse_score=0.8, dense_score=0.0),
    ]

    unauthorized = service._inject_enterprise_app_evidence(
        query,
        acl_filtered,
        groups={"HR"},
        environment="dev",
    )
    assert all(item.chunk.chunk_id != "portal-restricted" for item in unauthorized)

    authorized = service._inject_enterprise_app_evidence(
        query,
        acl_filtered,
        groups={"IT"},
        environment="dev",
    )
    assert any(item.chunk.chunk_id == "portal-restricted" for item in authorized)


def test_enterprise_app_inject_does_not_reintroduce_ineligible_chunks(
    tmp_path: Path,
) -> None:
    public_ad = DocumentChunk(
        chunk_id="ad-1",
        title="AD 帳號與系統解鎖 FAQ",
        source_path="sources/ad.md",
        content="帳號鎖定請至 AD 自助解鎖專區。",
    )
    placeholder_portal = DocumentChunk(
        chunk_id="portal-placeholder",
        title="國泰員工入口網",
        source_path="sources/portal-placeholder.md",
        content="企業級APP內將CATHAY LIFE加入驗證。",
        content_state="PLACEHOLDER",
    )
    index = HybridIndex([public_ad, placeholder_portal])
    service = HybridKnowledgeService(make_settings(tmp_path), index, model=None)
    injected = service._inject_enterprise_app_evidence(
        "來源所述的企業 App 無法使用應檢查什麼？",
        [SearchResult(chunk=public_ad, score=0.8, sparse_score=0.8, dense_score=0.0)],
        groups=set(),
        environment="dev",
    )
    assert all(item.chunk.chunk_id != "portal-placeholder" for item in injected)


def test_companion_inject_disabled_skips_temporary_rules(tmp_path: Path) -> None:
    public_ad = DocumentChunk(
        chunk_id="ad-1",
        title="AD 帳號與系統解鎖 FAQ",
        source_path="sources/ad.md",
        content="帳號鎖定請至 AD 自助解鎖專區。",
        allowed_groups=[],
    )
    portal = DocumentChunk(
        chunk_id="portal-1",
        title="國泰員工入口網、CTeam密碼、國泰e點名",
        source_path="sources/portal.md",
        content="企業級APP內將CATHAY LIFE加入驗證。",
        allowed_groups=[],
    )
    index = HybridIndex([public_ad, portal])
    service = HybridKnowledgeService(
        make_settings(tmp_path, rag_companion_inject_enabled=False),
        index,
        model=None,
    )
    results = [
        SearchResult(chunk=public_ad, score=0.8, sparse_score=0.8, dense_score=0.0),
    ]
    unchanged = service._inject_enterprise_app_evidence(
        "來源所述的企業 App 無法使用應檢查什麼？",
        results,
        groups=set(),
        environment="dev",
    )
    assert [item.chunk.chunk_id for item in unchanged] == ["ad-1"]


def test_policy_marked_security_advisory_is_retained() -> None:
    text = (
        "申請共用公槽請填必要資料 [S1]。\n"
        "系統資安政策要求遵守資料最小化 [POLICY-SEC-001]。"
    )
    common_keys = {"doc-1"}

    def _resolve(val: int) -> str | None:
        return "doc-1" if val == 1 else None

    cleaned = HybridKnowledgeService._prune_unbacked_sentences_and_citations(
        text,
        common_keys,
        _resolve,
    )
    assert "[POLICY-SEC-001]" in cleaned
    assert "資料最小化" in cleaned


@pytest.mark.asyncio
async def test_proxy_advisory_emits_policy_citation(tmp_path: Path) -> None:
    chunk = DocumentChunk(
        chunk_id="wifi-1",
        title="Wi-Fi 瞬斷處理",
        source_path="sources/wifi.md",
        content="若 Wi-Fi 瞬斷，可於個人裝置關閉 Proxy 後重新連線。",
    )
    index = HybridIndex([chunk])

    class ProxyAnswerModel:
        def with_structured_output(self, schema):
            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    if schema is RelevanceDecision:
                        return RelevanceDecision(relevant=True)
                    if schema is StructuredKnowledgeAnswer:
                        return StructuredKnowledgeAnswer(
                            answer="若 Wi-Fi 瞬斷，可關閉 Proxy 後重新連線 [S1]。",
                            answerability="FULL",
                            claims=[
                                GroundedClaim(
                                    text="若 Wi-Fi 瞬斷，可關閉 Proxy 後重新連線",
                                    chunkIds=["wifi-1"],
                                )
                            ],
                            unknowns=[],
                        )
                    if schema is GroundedClaimRepair:
                        return GroundedClaimRepair(claims=[])
                    raise NotImplementedError(schema)

            return _StructuredWrapper()

    service = HybridKnowledgeService(
        make_settings(tmp_path, top_k=1),
        index,
        model=ProxyAnswerModel(),
    )
    result = await service.search("Wi-Fi 瞬斷要關閉 Proxy 嗎？", make_user())
    assert result.found is True
    assert "[POLICY-SEC-003]" in result.answer
    policy_sources = [s for s in result.sources if s.sourceType == "POLICY_ADVISORY"]
    assert len(policy_sources) == 1
    assert policy_sources[0].chunkId == "POLICY-SEC-003"
    assert any(a.policyIds == ["POLICY-SEC-003"] for a in result.policyAdvisories)


@pytest.mark.asyncio
async def test_qb019_high_confidence_grounded_answer_is_not_rejected(tmp_path: Path) -> None:
    """Regression: retrieved VPN docs + valid claims must not become UNGROUNDED."""
    chunks = [
        DocumentChunk(
            chunk_id="vpn-jump",
            title="VPN 跳板機連線異常",
            source_path="sources/vpn-jump.md",
            content="跳板機連線異常時，請先確認 VPN 通道與跳板主機狀態。",
        ),
        DocumentChunk(
            chunk_id="vpn-faq",
            title="VPN 常見 Q&A",
            source_path="sources/vpn-faq.md",
            content="VPN 常見問題包含連線失敗與跳板機異常排查。",
        ),
        DocumentChunk(
            chunk_id="ad-faq",
            title="AD FAQ",
            source_path="sources/ad-faq.md",
            content="AD 帳號狀態可能影響 VPN 登入。",
        ),
    ]
    index = HybridIndex(chunks)

    class GroundedVpnModel:
        def with_structured_output(self, schema):
            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    if schema is RelevanceDecision:
                        return RelevanceDecision(relevant=True)
                    if schema is StructuredKnowledgeAnswer:
                        return StructuredKnowledgeAnswer(
                            answer="跳板機連線異常時請先確認 VPN 通道與跳板主機狀態 [S1]。",
                            answerability="FULL",
                            claims=[
                                GroundedClaim(
                                    text="跳板機連線異常時請先確認 VPN 通道與跳板主機狀態",
                                    chunkIds=["vpn-jump"],
                                )
                            ],
                            unknowns=[],
                        )
                    if schema is GroundedClaimRepair:
                        return GroundedClaimRepair(claims=[])
                    raise NotImplementedError(schema)

            return _StructuredWrapper()

    settings = make_settings(tmp_path, top_k=3, skip_relevance_llm_on_high_confidence=True)
    service = HybridKnowledgeService(settings, index, model=GroundedVpnModel())
    result = await service.search("VPN 跳板機連線異常怎麼辦？", make_user())

    assert result.found is True
    assert result.terminalReason != "UNGROUNDED_ANSWER"
    assert "[S1]" in result.answer
    assert result.sources
    assert result.claims
    assert result.retrievalTrace is not None
    assert result.retrievalTrace.claims


@pytest.mark.asyncio
async def test_qb097_pruned_answer_citations_stay_consistent(tmp_path: Path) -> None:
    """After pruning unbacked Outlook markers, answer markers and sources must match."""
    chunks = [
        DocumentChunk(
            chunk_id="phone-1",
            title="總公司IP話機操作",
            source_path="sources/phone.md",
            content="IP 話機轉接請按 Transfer。",
        ),
        DocumentChunk(
            chunk_id="outlook-ios",
            title="行動裝置 Outlook 安裝手冊（iOS）",
            source_path="sources/outlook-ios.md",
            content="iOS Outlook 首次設定步驟。",
        ),
        DocumentChunk(
            chunk_id="outlook-android",
            title="行動裝置 Outlook 安裝手冊（Android）",
            source_path="sources/outlook-android.md",
            content="Android Outlook 首次設定步驟。",
        ),
    ]
    index = HybridIndex(chunks)

    class MixedCitationModel:
        def with_structured_output(self, schema):
            class _StructuredWrapper:
                async def ainvoke(self, messages):
                    if schema is RelevanceDecision:
                        return RelevanceDecision(relevant=True)
                    if schema is StructuredKnowledgeAnswer:
                        return StructuredKnowledgeAnswer(
                            answer=(
                                "IP 話機轉接請按 Transfer [S1]。"
                                "iOS Outlook 步驟如下 [S2]。"
                                "Android Outlook 步驟如下 [S3]。"
                            ),
                            answerability="FULL",
                            claims=[
                                GroundedClaim(
                                    text="IP 話機轉接請按 Transfer",
                                    chunkIds=["phone-1"],
                                )
                            ],
                            unknowns=[],
                        )
                    if schema is GroundedClaimRepair:
                        return GroundedClaimRepair(
                            claims=[
                                GroundedClaim(
                                    text="IP 話機轉接請按 Transfer",
                                    chunkIds=["phone-1"],
                                )
                            ]
                        )
                    raise NotImplementedError(schema)

            return _StructuredWrapper()

    service = HybridKnowledgeService(
        make_settings(tmp_path, top_k=3),
        index,
        model=MixedCitationModel(),
    )
    result = await service.search("IP 話機如何轉接？", make_user())

    assert result.found is True
    assert "[S1]" in result.answer
    assert "[S2]" not in result.answer
    assert "[S3]" not in result.answer
    assert "iOS Outlook" not in result.answer
    assert "Android Outlook" not in result.answer
    assert len(result.sources) == 1
    assert result.sources[0].chunkId == "phone-1"
    assert all(s.sourceType != "POLICY_ADVISORY" or "[POLICY" in result.answer for s in result.sources)
