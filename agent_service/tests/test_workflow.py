"""Integration tests for the §5 LangGraph Agent Workflow (Task 9).

Every collaborator (Issue Extractor's model, Knowledge Service, Ticket
Service, Conversation Repository) is a small in-memory fake/stub — no
network calls, no real LLM. The point of this file is to prove the
*wiring*: correlation id propagation, non-blocking multi-issue processing,
FAQ verbatim/fallback, need-more-info, ticket creation gating (confirmation,
trusted identity, one-per-turn), LLM budget degradation, and the follow-up
(re-extract-with-history) flow.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_service.contracts import (
    AgentRequest,
    ConversationIdentity,
    FaqEntry,
    Issue,
    IssueExtraction,
    KnowledgeResult,
    MessageContent,
    Ticket,
    TicketItem,
    UserIdentity,
)
from agent_service.conversation import ConversationService, InMemoryConversationRepository
from agent_service.extractor import IssueExtractor
from agent_service.faq import FaqRepository, FaqService
from agent_service.response_builder import ALL_NON_IT_MESSAGE
from agent_service.settings import RagSettings
from agent_service.ticket import TicketServiceDisabledError
from agent_service.workflow import AgentWorkflow

# --- settings / request helpers -------------------------------------------


def make_settings(tmp_path: Path, **overrides) -> RagSettings:
    defaults: dict = {
        "data_dir": tmp_path,
        "index_path": tmp_path / "index.json",
        "ticket_service_mode": "HTTP",
        "ticket_service_base_url": "https://tickets.example.internal",
    }
    defaults.update(overrides)
    return RagSettings(**defaults)


def trusted_user(**overrides) -> UserIdentity:
    defaults = {"entraObjectId": "user-1", "displayName": "Alice", "email": "alice@example.com"}
    defaults.update(overrides)
    return UserIdentity(**defaults)


def make_request(
    text: str,
    *,
    correlation_id: str | None = None,
    conversation_id: str = "conv-1",
    user: UserIdentity | None = None,
) -> AgentRequest:
    return AgentRequest(
        requestId="req-1",
        channel="msteams",
        conversation=ConversationIdentity(tenantId="tenant-1", conversationId=conversation_id),
        user=user or trusted_user(),
        message=MessageContent(text=text, locale="zh-TW"),
        correlationId=correlation_id,
    )


# --- fakes -----------------------------------------------------------------


class _StructuredHandle:
    def __init__(self, result, recorder: list):
        self._result = result
        self._recorder = recorder

    async def ainvoke(self, messages):
        self._recorder.append(messages)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeExtractorModel:
    """Stands in for a BaseChatModel used only via with_structured_output.

    ``issues_sequence`` supplies one ``list[Issue]`` per extractor call, in
    order (so a follow-up turn can return a different set than the first).
    """

    def __init__(self, issues_sequence: list[list[Issue]]):
        self._sequence = list(issues_sequence)
        self.calls = 0
        self.human_messages: list[str] = []

    def with_structured_output(self, schema):
        assert schema is IssueExtraction
        self.calls += 1
        issues = self._sequence.pop(0) if self._sequence else []
        recorder: list = []
        handle = _StructuredHandle(IssueExtraction(issues=issues), recorder)
        # Peek at the human message content on ainvoke via a thin wrapper.
        outer_ainvoke = handle.ainvoke

        async def ainvoke(messages):
            for message in messages:
                self.human_messages.append(str(message.content))
            return await outer_ainvoke(messages)

        handle.ainvoke = ainvoke  # type: ignore[method-assign]
        return handle


class FakeKnowledgeService:
    """Maps a query string to a canned ``KnowledgeResult``."""

    def __init__(
        self,
        responses: dict[str, KnowledgeResult] | None = None,
        default: KnowledgeResult | None = None,
    ) -> None:
        self.responses = responses or {}
        self.default = default or KnowledgeResult(found=False, answer="", backend="FAKE")
        self.calls: list[str] = []
        self.received_correlation_ids: list[str | None] = []

    async def search(self, query, user_context, *, correlation_id=None, call_counter=None):
        self.calls.append(query)
        self.received_correlation_ids.append(correlation_id)
        if call_counter is not None:
            call_counter.increment()
        return self.responses.get(query, self.default)


class SelectiveFailKnowledgeService:
    """Raises for any query containing ``fail_marker``, else answers plainly."""

    def __init__(self, fail_marker: str = "FAILME") -> None:
        self.fail_marker = fail_marker
        self.calls: list[str] = []

    async def search(self, query, user_context, *, correlation_id=None, call_counter=None):
        self.calls.append(query)
        if call_counter is not None:
            call_counter.increment()
        if self.fail_marker in query:
            raise RuntimeError("knowledge backend exploded")
        return KnowledgeResult(found=True, answer=f"根據資料，{query} 的處理方式如下。", backend="HYBRID")


class FlakyFaqService:
    """Wraps a real FaqService but forces ``get()`` misses for given keys.

    Used to exercise "FAQ route chosen at extraction time, but the lookup
    misses when Process Issues actually asks" without depending on the
    Issue Extractor's own coercion (which would otherwise reroute an
    unknown/disabled key to KNOWLEDGE before Process Issues ever runs).
    """

    def __init__(self, inner: FaqService, miss_keys: set[str]) -> None:
        self._inner = inner
        self._miss_keys = miss_keys

    def get(self, faq_key: str):
        if faq_key in self._miss_keys:
            return None
        return self._inner.get(faq_key)

    def available_keys(self) -> list[str]:
        return self._inner.available_keys()


class FakeTicketService:
    def __init__(self) -> None:
        self.created: list = []
        self.list_calls: list[str] = []
        self.items = [TicketItem(id="item-1", name="General Support")]
        self._by_requester: dict[str, list[Ticket]] = {}

    async def get_ticket_items(self, *, correlation_id=None):
        return self.items

    async def create_ticket(self, draft, *, correlation_id=None):
        self.created.append((draft, correlation_id))
        ticket = Ticket(
            id=f"TCK-{len(self.created)}",
            title=draft.title,
            status="OPEN",
            url="https://tickets.example.internal/TCK-1",
        )
        self._by_requester.setdefault(draft.requesterId, []).append(ticket)
        return ticket

    async def list_tickets_by_requester(self, requester_id, *, correlation_id=None):
        self.list_calls.append(requester_id)
        return self._by_requester.get(requester_id, [])

    async def get_ticket(self, ticket_id, requester_id, *, correlation_id=None):
        for ticket in self._by_requester.get(requester_id, []):
            if ticket.id == ticket_id:
                return ticket
        return None


class DisabledFakeTicketService:
    async def get_ticket_items(self, *, correlation_id=None):
        raise TicketServiceDisabledError()

    async def create_ticket(self, draft, *, correlation_id=None):
        raise TicketServiceDisabledError()

    async def list_tickets_by_requester(self, requester_id, *, correlation_id=None):
        raise TicketServiceDisabledError()

    async def get_ticket(self, ticket_id, requester_id, *, correlation_id=None):
        raise TicketServiceDisabledError()


def make_conversation_service(settings: RagSettings) -> ConversationService:
    return ConversationService(
        InMemoryConversationRepository(clock=lambda: datetime.now(timezone.utc)), settings
    )


def issue(**overrides) -> Issue:
    base = {
        "id": 1,
        "description": "VPN 無法連線",
        "isIT": True,
        "readiness": "READY",
        "missingInfo": [],
        "route": "KNOWLEDGE",
        "faqKey": None,
        "ticketAction": None,
    }
    base.update(overrides)
    return Issue(**base)


def build_workflow(
    tmp_path: Path,
    *,
    issues_sequence: list[list[Issue]],
    knowledge=None,
    ticket_service=None,
    faq_service: FaqService | None = None,
    settings_overrides: dict | None = None,
    conversation_service: ConversationService | None = None,
):
    settings = make_settings(tmp_path, **(settings_overrides or {}))
    extractor_model = FakeExtractorModel(issues_sequence)
    extractor = IssueExtractor(settings, model=extractor_model)
    faq = faq_service or FaqService(FaqRepository([]))
    knowledge_service = knowledge or FakeKnowledgeService()
    conv_service = conversation_service or make_conversation_service(settings)
    ticket = ticket_service or FakeTicketService()
    workflow = AgentWorkflow(
        settings,
        extractor=extractor,
        faq_service=faq,
        knowledge_service=knowledge_service,
        conversation_service=conv_service,
        ticket_service=ticket,
    )
    return workflow, extractor_model, knowledge_service, ticket, conv_service, settings


# --- tests -------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_it_issue_end_to_end(tmp_path: Path) -> None:
    it_issue = issue(id=1, description="VPN 無法連線")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(
            found=True, answer="請重新安裝 VPN 用戶端。", sources=[], images=[], backend="HYBRID"
        )
    )
    workflow, *_ = build_workflow(tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge)

    response = await workflow.respond(make_request("VPN 無法連線"))

    assert "請重新安裝 VPN 用戶端" in response.answer
    assert len(response.issueResults) == 1
    assert response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert response.correlationId
    assert response.traceId == response.correlationId


@pytest.mark.asyncio
async def test_multi_issue_one_failed_one_answered_both_surface(tmp_path: Path) -> None:
    issue1 = issue(id=1, description="FAILME 案例")
    issue2 = issue(id=2, description="正常案例")
    knowledge = SelectiveFailKnowledgeService()
    workflow, *_ = build_workflow(
        tmp_path, issues_sequence=[[issue1, issue2]], knowledge=knowledge
    )

    response = await workflow.respond(make_request("兩個問題"))

    result_types = {r.issueId: r.resultType for r in response.issueResults}
    assert result_types[1] == "FAILED"
    assert result_types[2] == "KNOWLEDGE_ANSWERED"
    # The failure never leaks internals into the user-facing text.
    assert "boom" not in response.answer
    assert "exploded" not in response.answer
    assert "正常案例" in response.answer


@pytest.mark.asyncio
async def test_faq_hit_answered_verbatim(tmp_path: Path) -> None:
    entry = FaqEntry(id="1", faqKey="PW_RESET", enabled=True, answer="請至公司密碼管理入口重設密碼。")
    faq_service = FaqService(FaqRepository([entry]))
    it_issue = issue(id=1, description="忘記密碼", route="FAQ", faqKey="PW_RESET")
    workflow, *_ = build_workflow(
        tmp_path, issues_sequence=[[it_issue]], faq_service=faq_service
    )

    response = await workflow.respond(make_request("忘記密碼怎麼辦"))

    assert response.issueResults[0].resultType == "FAQ_ANSWERED"
    assert response.issueResults[0].answer == entry.answer
    assert entry.answer in response.answer


@pytest.mark.asyncio
async def test_faq_miss_falls_back_to_knowledge(tmp_path: Path) -> None:
    entry = FaqEntry(id="1", faqKey="MISS_KEY", enabled=True, answer="不應該被使用的答案")
    real_faq = FaqService(FaqRepository([entry]))
    flaky_faq = FlakyFaqService(real_faq, miss_keys={"MISS_KEY"})
    it_issue = issue(id=1, description="某個問題", route="FAQ", faqKey="MISS_KEY")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="來自知識庫的答案", backend="HYBRID")
    )
    workflow, *_ = build_workflow(
        tmp_path, issues_sequence=[[it_issue]], faq_service=flaky_faq, knowledge=knowledge
    )

    response = await workflow.respond(make_request("某個問題"))

    assert response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert "來自知識庫的答案" in response.answer
    assert knowledge.calls == ["某個問題"]


@pytest.mark.asyncio
async def test_need_more_info_path(tmp_path: Path) -> None:
    it_issue = issue(
        id=1,
        description="VPN 問題",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的 VPN 應用程式名稱", "錯誤訊息或錯誤碼"],
    )
    workflow, *_ = build_workflow(tmp_path, issues_sequence=[[it_issue]])

    response = await workflow.respond(make_request("VPN 有問題"))

    result = response.issueResults[0]
    assert result.resultType == "NEED_MORE_INFO"
    assert result.questions == ["使用的 VPN 應用程式名稱", "錯誤訊息或錯誤碼"]
    assert "請補充" in response.answer


@pytest.mark.asyncio
async def test_all_non_it_issues(tmp_path: Path) -> None:
    issues = [
        issue(id=1, description="天氣", isIT=False, readiness="NOT_IT", route="NOT_IT"),
        issue(id=2, description="午餐", isIT=False, readiness="NOT_IT", route="NOT_IT"),
    ]
    workflow, *_ = build_workflow(tmp_path, issues_sequence=[issues])

    response = await workflow.respond(make_request("今天天氣如何？午餐吃什麼？"))

    assert response.answer == ALL_NON_IT_MESSAGE
    assert response.issueResults == []


@pytest.mark.asyncio
async def test_more_than_max_issues_asks_to_prioritize(tmp_path: Path) -> None:
    issues = [issue(id=i, description=f"問題{i}") for i in range(1, 5)]
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="OK", backend="HYBRID")
    )
    workflow, *_ = build_workflow(tmp_path, issues_sequence=[issues], knowledge=knowledge)

    response = await workflow.respond(make_request("四個問題一次問"))

    assert "已先協助你處理最重要的" in response.answer
    assert len(response.issueResults) == 3  # default MAX_ISSUES_PER_MESSAGE


@pytest.mark.asyncio
async def test_correlation_id_propagates_and_is_not_regenerated(tmp_path: Path) -> None:
    it_issue = issue(id=1, description="VPN 無法連線")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="答案", backend="HYBRID")
    )
    workflow, _model, knowledge, _ticket, conv_service, _settings = build_workflow(
        tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge
    )
    request = make_request("VPN 無法連線", correlation_id="caller-supplied-corr-id")

    response = await workflow.respond(request)

    assert response.correlationId == "caller-supplied-corr-id"
    assert response.traceId == "caller-supplied-corr-id"
    assert knowledge.received_correlation_ids == ["caller-supplied-corr-id"]

    history = await conv_service.get_history((await workflow.run(request)).get("conversation").conversationId)
    # Every saved message in this conversation carries the same correlation id.
    assert all(message.correlationId == "caller-supplied-corr-id" for message in history[:2])


@pytest.mark.asyncio
async def test_ticket_not_created_without_explicit_confirmation(tmp_path: Path) -> None:
    it_issue = issue(id=1, description="VPN 一直斷線", route="TICKET")
    ticket_service = FakeTicketService()
    workflow, *_ = build_workflow(
        tmp_path, issues_sequence=[[it_issue]], ticket_service=ticket_service
    )

    response = await workflow.respond(make_request("可能要報修"))

    assert ticket_service.created == []
    assert response.issueResults[0].resultType != "TICKET_CREATED"


@pytest.mark.asyncio
async def test_ticket_cancellation_short_circuits_retrieval_ticket_api_and_feedback(
    tmp_path: Path,
) -> None:
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="不應該被查詢", backend="HYBRID")
    )
    ticket_service = FakeTicketService()
    workflow, extractor_model, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[issue(route="TICKET")]],
        knowledge=knowledge,
        ticket_service=ticket_service,
        settings_overrides={"feedback_enabled": True},
    )

    response = await workflow.respond(make_request("不知道，先不要建立工單"))

    assert extractor_model.calls == 0
    assert knowledge.calls == []
    assert ticket_service.created == []
    assert ticket_service.list_calls == []
    assert response.issueResults[0].resultType == "TICKET_CANCELLED"
    assert response.answer == "好的，目前不會建立工單。若之後需要協助，請告訴我「建立工單」。"
    assert response.citations == []
    assert response.images == []
    assert response.feedbackEnabled is False


@pytest.mark.asyncio
async def test_ticket_delete_is_safely_denied_without_retrieval_or_ticket_api(
    tmp_path: Path,
) -> None:
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="不應該被查詢", backend="HYBRID")
    )
    ticket_service = FakeTicketService()
    workflow, extractor_model, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[issue(route="TICKET")]],
        knowledge=knowledge,
        ticket_service=ticket_service,
        settings_overrides={"feedback_enabled": True},
    )

    denied = await workflow.respond(make_request("刪除工單"))
    follow_up = await workflow.respond(make_request("是"))

    assert extractor_model.calls == 1  # only the later standalone "是"
    assert knowledge.calls == []
    assert ticket_service.created == []
    assert ticket_service.list_calls == []
    assert denied.issueResults[0].resultType == "TICKET_DELETE_DENIED"
    assert denied.answer.startswith("目前不支援刪除工單")
    assert denied.citations == []
    assert denied.images == []
    assert denied.feedbackEnabled is False
    assert follow_up.issueResults[0].resultType != "TICKET_CREATED"


@pytest.mark.asyncio
async def test_yes_after_cancellation_cannot_reuse_a_pending_ticket_offer(tmp_path: Path) -> None:
    ticket_service = FakeTicketService()
    workflow, _extractor_model, knowledge, *_ = build_workflow(
        tmp_path,
        # First produce a real pending offer. After cancellation, this
        # simulates a bad extractor route on the later bare "是".
        issues_sequence=[
            [issue(description="VPN Error 619", route="KNOWLEDGE")],
            [issue(description="VPN Error 619", route="TICKET")],
        ],
        ticket_service=ticket_service,
    )

    offered = await workflow.respond(make_request("VPN Error 619"))
    cancelled = await workflow.respond(make_request("先不要建立工單"))
    follow_up = await workflow.respond(make_request("是"))

    assert "是否需要協助建立工單" in offered.answer
    assert cancelled.issueResults[0].resultType == "TICKET_CANCELLED"
    assert ticket_service.created == []
    assert ticket_service.list_calls == []
    assert follow_up.issueResults[0].resultType != "TICKET_CREATED"
    assert knowledge.calls == ["VPN Error 619"]


@pytest.mark.asyncio
async def test_yes_creates_ticket_only_when_previous_turn_contains_live_offer(
    tmp_path: Path,
) -> None:
    ticket_service = FakeTicketService()
    workflow, _extractor_model, knowledge, *_ = build_workflow(
        tmp_path,
        issues_sequence=[
            [issue(description="VPN Error 619", route="KNOWLEDGE")],
            [issue(description="VPN Error 619", route="KNOWLEDGE")],
        ],
        ticket_service=ticket_service,
    )

    offered = await workflow.respond(make_request("VPN Error 619"))
    confirmed = await workflow.respond(make_request("是"))

    assert "是否需要協助建立工單" in offered.answer
    assert len(ticket_service.created) == 1
    assert ticket_service.created[0][0].description == "VPN Error 619"
    assert confirmed.issueResults[0].resultType == "TICKET_CREATED"
    assert knowledge.calls == ["VPN Error 619"]


@pytest.mark.asyncio
async def test_yes_merges_multiple_pending_issues_into_one_ticket(tmp_path: Path) -> None:
    ticket_service = FakeTicketService()
    workflow, _extractor_model, knowledge, *_ = build_workflow(
        tmp_path,
        issues_sequence=[
            [
                issue(id=1, description="VPN Error 619", route="KNOWLEDGE"),
                issue(id=2, description="SAP 密碼無法重置", route="KNOWLEDGE"),
            ],
            [
                issue(id=1, description="VPN Error 619 建立工單", route="TICKET"),
                issue(id=2, description="SAP 密碼無法重置 建立工單", route="TICKET"),
            ],
        ],
        ticket_service=ticket_service,
    )

    offered = await workflow.respond(
        make_request("VPN Error 619，而且 SAP 密碼也無法重置")
    )
    confirmed = await workflow.respond(make_request("是"))

    assert offered.answer.count("是否需要協助建立工單") == 2
    assert len(ticket_service.created) == 1
    draft, _correlation_id = ticket_service.created[0]
    assert "VPN Error 619" in draft.description
    assert "SAP 密碼無法重置" in draft.description
    assert "建立工單" not in draft.description
    assert draft.description == "VPN Error 619；SAP 密碼無法重置"
    assert len(confirmed.issueResults) == 1
    assert confirmed.issueResults[0].resultType == "TICKET_CREATED"
    assert "處理時發生問題" not in confirmed.answer
    assert knowledge.calls == ["VPN Error 619", "SAP 密碼無法重置"]
    assert _extractor_model.calls == 1


@pytest.mark.asyncio
async def test_ticket_created_after_explicit_confirmation_with_trusted_identity(
    tmp_path: Path,
) -> None:
    it_issue = issue(id=1, description="VPN 一直斷線", route="TICKET")
    ticket_service = FakeTicketService()
    workflow, *_ = build_workflow(
        tmp_path, issues_sequence=[[it_issue]], ticket_service=ticket_service
    )

    response = await workflow.respond(
        make_request("請幫我建立工單", user=trusted_user())
    )

    assert len(ticket_service.created) == 1
    result = response.issueResults[0]
    assert result.resultType == "TICKET_CREATED"
    assert result.ticketId
    assert "已為你建立工單" in response.answer


@pytest.mark.asyncio
async def test_ticket_refused_when_identity_untrusted(tmp_path: Path) -> None:
    it_issue = issue(id=1, description="VPN 一直斷線", route="TICKET")
    ticket_service = FakeTicketService()
    workflow, *_ = build_workflow(
        tmp_path, issues_sequence=[[it_issue]], ticket_service=ticket_service
    )
    untrusted = UserIdentity(teamsUserId="teams-1")  # missing displayName/email

    response = await workflow.respond(
        make_request("請幫我建立工單", user=untrusted)
    )

    assert ticket_service.created == []
    assert response.issueResults[0].resultType == "FAILED"
    assert "untrusted_requester" not in response.answer


@pytest.mark.asyncio
async def test_one_ticket_per_turn(tmp_path: Path) -> None:
    issue1 = issue(id=1, description="VPN 斷線", route="TICKET")
    issue2 = issue(id=2, description="Outlook 當機", route="TICKET")
    ticket_service = FakeTicketService()
    workflow, *_ = build_workflow(
        tmp_path, issues_sequence=[[issue1, issue2]], ticket_service=ticket_service
    )

    response = await workflow.respond(make_request("請幫我建立工單"))

    assert len(ticket_service.created) == 1
    created_types = [r.resultType for r in response.issueResults]
    assert created_types.count("TICKET_CREATED") == 1


@pytest.mark.asyncio
async def test_explicit_multi_problem_creation_builds_one_ticket_without_retrieval(
    tmp_path: Path,
) -> None:
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="不應該被查詢", backend="HYBRID")
    )
    ticket_service = FakeTicketService()
    workflow, extractor_model, *_ = build_workflow(
        tmp_path,
        issues_sequence=[
            [
                issue(id=1, description="VPN Error 619"),
                issue(id=2, description="SAP 密碼也無法重置"),
                issue(id=3, description="請建立工單", route="TICKET"),
            ]
        ],
        knowledge=knowledge,
        ticket_service=ticket_service,
    )

    response = await workflow.respond(
        make_request("VPN Error 619，而且 SAP 密碼也無法重置，請建立工單")
    )

    assert extractor_model.calls == 0
    assert knowledge.calls == []
    assert len(ticket_service.created) == 1
    draft, _correlation_id = ticket_service.created[0]
    assert "VPN Error 619" in draft.title
    assert "SAP 密碼也無法重置" in draft.title
    assert "VPN Error 619" in draft.description
    assert "SAP 密碼也無法重置" in draft.description
    assert len(response.issueResults) == 1
    assert response.issueResults[0].resultType == "TICKET_CREATED"


@pytest.mark.asyncio
async def test_disabled_ticket_service_degrades_gracefully(tmp_path: Path) -> None:
    it_issue = issue(id=1, description="VPN 斷線", route="TICKET")
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[it_issue]],
        ticket_service=DisabledFakeTicketService(),
        settings_overrides={"ticket_service_mode": "DISABLED"},
    )

    response = await workflow.respond(make_request("請幫我建立工單"))

    assert response.issueResults[0].resultType == "FAILED"
    assert "TicketServiceDisabledError" not in response.answer
    assert response.answer  # a safe message was still produced, not a crash


@pytest.mark.asyncio
async def test_llm_budget_cap_degrades_remaining_issues(tmp_path: Path) -> None:
    issues = [issue(id=i, description=f"問題{i}") for i in range(1, 4)]
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="不應該被呼叫", backend="HYBRID")
    )
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[issues],
        knowledge=knowledge,
        settings_overrides={"max_llm_calls_per_request": 1},
    )

    response = await workflow.respond(make_request("三個問題"))

    # The extractor call alone already consumes the budget (1), so no
    # knowledge-service call should ever happen.
    assert knowledge.calls == []
    assert all(r.resultType == "NO_KNOWLEDGE" for r in response.issueResults)
    assert "不應該被呼叫" not in response.answer


@pytest.mark.asyncio
async def test_follow_up_supplies_missing_info_and_re_extracts_with_history(
    tmp_path: Path,
) -> None:
    first_turn_issue = issue(
        id=1,
        description="VPN 有問題",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的 VPN 應用程式名稱", "錯誤訊息或錯誤碼"],
    )
    second_turn_issue = issue(id=1, description="Cisco AnyConnect 錯誤 691", readiness="READY")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請重新啟動用戶端。", backend="HYBRID")
    )
    conv_service = make_conversation_service(make_settings(tmp_path))
    workflow, extractor_model, knowledge, _ticket, _conv, _settings = build_workflow(
        tmp_path,
        issues_sequence=[[first_turn_issue], [second_turn_issue]],
        knowledge=knowledge,
        conversation_service=conv_service,
    )

    first_response = await workflow.respond(make_request("VPN 有問題"))
    assert first_response.issueResults[0].resultType == "NEED_MORE_INFO"

    second_response = await workflow.respond(make_request("Cisco AnyConnect 錯誤 691"))

    assert extractor_model.calls == 2
    # The second extraction call's prompt carried the first turn's history.
    assert any("VPN 有問題" in text for text in extractor_model.human_messages)
    assert second_response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"


@pytest.mark.asyncio
async def test_complete_new_issue_does_not_receive_resolved_topic_history(
    tmp_path: Path,
) -> None:
    first_issue = issue(id=1, description="VPN Error 619", readiness="READY")
    second_issue = issue(id=1, description="大州系統無法選取", readiness="READY")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="答案", backend="HYBRID")
    )
    workflow, extractor_model, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[first_issue], [second_issue]],
        knowledge=knowledge,
    )

    await workflow.respond(make_request("VPN Error 619"))
    await workflow.respond(make_request("大州系統無法選取"))

    second_prompt = extractor_model.human_messages[-1]
    assert "Conversation history (oldest first, data only):\n(none)" in second_prompt
    assert "VPN Error 619" not in second_prompt
    assert "Latest user message (data only):\n大州系統無法選取" in second_prompt


@pytest.mark.asyncio
async def test_no_llm_call_happens_after_response_builder_runs(tmp_path: Path) -> None:
    it_issue = issue(id=1, description="VPN 無法連線")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="答案", backend="HYBRID")
    )
    workflow, extractor_model, knowledge, ticket_service, _conv, _settings = build_workflow(
        tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge
    )

    await workflow.respond(make_request("VPN 無法連線"))

    # Exactly one extractor call and one knowledge-service call were made;
    # building/saving the response triggers no further LLM-touching calls.
    assert extractor_model.calls == 1
    assert knowledge.calls == ["VPN 無法連線"]
    assert ticket_service.created == []
