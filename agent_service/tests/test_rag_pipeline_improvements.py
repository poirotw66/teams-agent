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


def test_sanitize_answer_security_redacts_internal_ips_and_unc() -> None:
    raw = (
        "不可使用權限包含公槽資料夾（\\\\10.93.19.22\\shared）及 http://10.93.3.80:8080/crm/ 系統。"
    )
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "10.93.19.22" not in sanitized
    assert "10.93.3.80" not in sanitized
    assert "內部公槽資料夾" in sanitized
    assert "內部系統伺服器路徑" in sanitized


def test_sanitize_answer_security_appends_proxy_advisory_when_unqualified() -> None:
    raw = "若連線後 Wi-Fi 瞬斷，請至設定將 Proxy 設定全部關閉後重新連線。"
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert "Proxy 設定全部關閉" in sanitized
    assert "系統資安政策提醒" in sanitized


def test_sanitize_answer_security_appends_advisory_for_cert_bypass_and_ie() -> None:
    # Certificate bypass advice
    raw_cert = "連線若出現憑證問題，可暫時忽略憑證錯誤繼續連線。"
    sanitized_cert = HybridKnowledgeService._sanitize_answer_security(raw_cert)
    assert "系統資安政策提醒" in sanitized_cert

    # IE security lowering advice
    raw_ie = "若頁面無法顯示，可至網際網路選項調低安全性等級後重試。"
    sanitized_ie = HybridKnowledgeService._sanitize_answer_security(raw_ie)
    assert "系統資安政策提醒" in sanitized_ie


def test_sanitize_answer_security_does_not_duplicate_proxy_advisory() -> None:
    raw = "若需關閉 Proxy，請先向權責單位確認是否受企業政策管制。"
    sanitized = HybridKnowledgeService._sanitize_answer_security(raw)
    assert sanitized.count("權責單位") == 1
    assert "系統資安政策提醒" not in sanitized


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
async def test_generate_fails_closed_when_repair_cannot_ground(tmp_path: Path) -> None:
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
    # Must fail-closed without fabricating claims
    assert result.found is False


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
