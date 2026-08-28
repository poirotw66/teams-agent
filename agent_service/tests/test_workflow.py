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

import itertools
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_service.confirmation import TicketIntent, classify_ticket_intent
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
from agent_service.handoff import HandoffStatus, InMemoryHandoffRepository
from agent_service.handoff_flow import HandoffAction, TicketQueryDecision
from agent_service.settings import RagSettings
from agent_service.ticket import TicketItemSelection, TicketServiceDisabledError
from agent_service.ticket_dedupe import InMemoryTicketRequestDedupeRepository
from agent_service.workflow import AgentWorkflow

# --- settings / request helpers -------------------------------------------

_REQUEST_IDS = itertools.count(1)


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
    request_id: str | None = None,
    correlation_id: str | None = None,
    conversation_id: str = "conv-1",
    user: UserIdentity | None = None,
) -> AgentRequest:
    resolved_request_id = request_id or f"req-{next(_REQUEST_IDS)}"
    return AgentRequest(
        requestId=resolved_request_id,
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
    ``by_message`` overrides the sequence when the latest user message matches
    exactly — needed when deterministic bypass paths skip model calls.
    """

    def __init__(
        self,
        issues_sequence: list[list[Issue]],
        *,
        by_message: dict[str, list[Issue]] | None = None,
    ):
        self._sequence = list(issues_sequence)
        self.by_message = by_message or {}
        self.calls = 0
        self.human_messages: list[str] = []

    @staticmethod
    def _latest_user_message(messages) -> str:
        for message in reversed(messages):
            content = str(message.content)
            marker = "Latest user message (data only):\n"
            if marker in content:
                return content.split(marker, 1)[1].strip()
        return ""

    def with_structured_output(self, schema):
        if schema is TicketQueryDecision:
            class TicketQueryHandle:
                async def ainvoke(self, messages):
                    text = FakeExtractorModel._latest_user_message(messages)
                    is_query = classify_ticket_intent(text) == TicketIntent.QUERY
                    return TicketQueryDecision(is_ticket_query=is_query)

            return TicketQueryHandle()

        assert schema is IssueExtraction
        outer = self

        class Handle:
            async def ainvoke(self, messages):
                outer.calls += 1
                for message in messages:
                    outer.human_messages.append(str(message.content))
                text = FakeExtractorModel._latest_user_message(messages)
                if text in outer.by_message:
                    issues = outer.by_message[text]
                else:
                    issues = outer._sequence.pop(0) if outer._sequence else []
                return IssueExtraction(issues=issues)

        return Handle()


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

    async def create_ticket(self, draft, *, correlation_id=None, idempotency_key=None):
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

    async def create_ticket(self, draft, *, correlation_id=None, idempotency_key=None):
        raise TicketServiceDisabledError()

    async def list_tickets_by_requester(self, requester_id, *, correlation_id=None):
        raise TicketServiceDisabledError()

    async def get_ticket(self, ticket_id, requester_id, *, correlation_id=None):
        raise TicketServiceDisabledError()


class FakeHandoffRouter:
    def __init__(self, actions: list[HandoffAction]) -> None:
        self.actions = list(actions)

    async def decide(
        self,
        *,
        message: str,
        case_status: str,
        **_kwargs,
    ) -> HandoffAction:
        from agent_service.confirmation import TicketIntent, classify_ticket_intent
        from agent_service.handoff_flow import (
            _protocol_close_command,
            classify_summary_review_action,
        )

        if case_status == "DEMO_ACTIVE" and _protocol_close_command(message):
            return HandoffAction.CLOSE
        if case_status == "DEMO_ACTIVE" and classify_ticket_intent(message) == TicketIntent.CREATE:
            return HandoffAction.CREATE_TICKET
        if case_status == "SUMMARY_REVIEW":
            explicit = classify_summary_review_action(message)
            if explicit is not None:
                return explicit
        if not self.actions:
            return HandoffAction.UNKNOWN
        return self.actions.pop(0)


class FakeTicketQueryRouter:
    def __init__(self, *, ticket_queries: set[str] | None = None) -> None:
        self.ticket_queries = ticket_queries or set()
        self.calls = 0

    async def is_ticket_query(
        self,
        *,
        message: str,
        conversation_turns=(),
        execution_context=None,
    ) -> bool:
        self.calls += 1
        return message in self.ticket_queries


class FakeTicketItemSelector:
    """Test double for the model-driven catalog selector."""

    def __init__(self, item_id: str | None = None, reason: str = "selected") -> None:
        self.item_id = item_id
        self.reason = reason

    async def select(self, *, items, issue_description, execution_context=None):
        selected = next((item for item in items if item.id == self.item_id), None)
        if self.item_id is None and self.reason == "selected":
            selected = items[0] if items else None
        return TicketItemSelection(item=selected, reason=self.reason)


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
    handoff_repository=None,
    handoff_router=None,
    ticket_query_router=None,
    ticket_item_selector=None,
    ticket_request_dedupe=None,
    extractor_by_message: dict[str, list[Issue]] | None = None,
):
    settings = make_settings(tmp_path, **(settings_overrides or {}))
    extractor_model = FakeExtractorModel(
        issues_sequence, by_message=extractor_by_message
    )
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
        handoff_repository=handoff_repository,
        handoff_router=handoff_router,
        ticket_query_router=ticket_query_router,
        ticket_item_selector=ticket_item_selector or FakeTicketItemSelector(),
        ticket_request_dedupe=ticket_request_dedupe
        or InMemoryTicketRequestDedupeRepository(),
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
async def test_new_question_supersedes_handoff_review_and_returns_to_ai(
    tmp_path: Path,
) -> None:
    sap_issue = issue(description="SAP Crystal Reports 授權到期無法開啟")
    vpn_issue = issue(description="VPN 密碼鎖住怎麼辦")
    knowledge = FakeKnowledgeService(
        responses={
            sap_issue.description: KnowledgeResult(
                found=False, answer="", backend="HYBRID"
            ),
            vpn_issue.description: KnowledgeResult(
                found=True,
                answer="請依 VPN 密碼解鎖流程處理。",
                backend="HYBRID",
            ),
        }
    )
    repository = InMemoryHandoffRepository()
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[sap_issue], [vpn_issue]],
        knowledge=knowledge,
        handoff_repository=repository,
        handoff_router=FakeHandoffRouter([HandoffAction.NEW_ISSUE]),
    )

    offered = await workflow.respond(make_request(sap_issue.description))
    active = await repository.get_active_case("tenant-1", "conv-1", "user-1")
    assert active is not None

    answered = await workflow.respond(make_request(vpn_issue.description))
    stored = await repository.get_case(active.caseId)

    assert "請依 VPN 密碼解鎖流程處理" in answered.answer
    assert "SAP Crystal Reports" not in answered.answer
    assert stored is not None and stored.status == HandoffStatus.CANCELLED
    assert offered.answer.startswith("目前無法從企業知識庫找到可確認的答案")
    assert knowledge.calls == [sap_issue.description, vpn_issue.description]


@pytest.mark.asyncio
async def test_handoff_summary_changes_only_after_explicit_supplement_action(
    tmp_path: Path,
) -> None:
    sap_issue = issue(description="SAP Crystal Reports 授權到期無法開啟")
    repository = InMemoryHandoffRepository()
    workflow, extractor_model, knowledge, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[sap_issue]],
        knowledge=FakeKnowledgeService(),
        handoff_repository=repository,
        handoff_router=FakeHandoffRouter([HandoffAction.SUPPLEMENT]),
    )

    await workflow.respond(make_request(sap_issue.description))
    prompt = await workflow.respond(make_request("繼續補充"))
    supplemented = await workflow.respond(make_request("錯誤碼 CR-1001"))
    active = await repository.get_active_case("tenant-1", "conv-1", "user-1")

    assert prompt.answer.startswith("請繼續補充問題")
    assert "問題：SAP Crystal Reports 授權到期無法開啟" in supplemented.answer
    assert "使用者需求：錯誤碼 CR-1001" in supplemented.answer
    assert active is not None and active.status == HandoffStatus.SUMMARY_REVIEW
    assert active.summary.conversationHighlights == ["錯誤碼 CR-1001"]
    assert extractor_model.calls == 1
    assert knowledge.calls == [sap_issue.description]


@pytest.mark.asyncio
async def test_unknown_handoff_action_keeps_summary_review_case(tmp_path: Path) -> None:
    sap_issue = issue(description="SAP Crystal Reports 授權到期無法開啟")
    repository = InMemoryHandoffRepository()
    workflow, extractor_model, knowledge, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[sap_issue]],
        knowledge=FakeKnowledgeService(
            responses={
                sap_issue.description: KnowledgeResult(
                    found=False, answer="", backend="HYBRID"
                )
            }
        ),
        handoff_repository=repository,
        handoff_router=FakeHandoffRouter([HandoffAction.UNKNOWN]),
    )

    offered = await workflow.respond(make_request(sap_issue.description))
    active = await repository.get_active_case("tenant-1", "conv-1", "user-1")
    assert active is not None

    retried = await workflow.respond(make_request("意圖不明的文字"))
    stored = await repository.get_case(active.caseId)

    assert retried.answer == offered.answer
    assert stored is not None and stored.status == HandoffStatus.SUMMARY_REVIEW
    assert extractor_model.calls == 1
    assert knowledge.calls == [sap_issue.description]


@pytest.mark.parametrize("text", ["有哪些派工單", "有哪些工單"])
@pytest.mark.asyncio
async def test_ticket_list_queries_current_users_dispatch_tickets_not_faq(
    tmp_path: Path, text: str
) -> None:
    faq = FaqService(
        FaqRepository([FaqEntry(id="1", faqKey="TICKET_FAQ", enabled=True, answer="FAQ")])
    )
    ticket_service = FakeTicketService()
    ticket_service._by_requester["user-1"] = [
        Ticket(id="TCK-1", title="VPN 問題", status="OPEN", url="https://tickets/TCK-1")
    ]
    workflow, extractor_model, knowledge, _ticket, *_ = build_workflow(
        tmp_path,
        # This would produce an FAQ response if the agentic ticket-query
        # decision did not intercept the message first.
        issues_sequence=[[issue(route="FAQ", faqKey="TICKET_FAQ")]],
        faq_service=faq,
        ticket_service=ticket_service,
        ticket_query_router=FakeTicketQueryRouter(
            ticket_queries={"有哪些派工單", "有哪些工單"}
        ),
    )

    response = await workflow.respond(make_request(text))

    assert extractor_model.calls == 0
    assert knowledge.calls == []
    assert ticket_service.list_calls == ["user-1"]
    assert response.issueResults[0].resultType == "TICKET_FOUND"
    assert "你的派工單如下：" in response.answer
    assert "問題：查詢目前使用者的派工單" in response.answer


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

    assert "「天氣」、「午餐」不屬於公司 IT 支援範圍" in response.answer
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
        tmp_path,
        issues_sequence=[[it_issue]],
        ticket_service=ticket_service,
        ticket_item_selector=FakeTicketItemSelector("item-vpn"),
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
    assert response.answer == "好的，目前不會建立派工單。若之後需要協助，請告訴我「建立派工單」。"
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
    assert denied.answer.startswith("目前不支援刪除派工單")
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

    assert "是否需要協助建立派工單" in offered.answer
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

    assert "是否需要協助建立派工單" in offered.answer
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

    assert offered.answer.count("是否需要協助建立派工單") == 2
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
    ticket_service.items = [
        TicketItem(id="item-power", name="電腦無法開機", level=3),
        TicketItem(id="item-vpn", name="VPN 無法連線", level=3),
    ]
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[it_issue]],
        ticket_service=ticket_service,
        ticket_item_selector=FakeTicketItemSelector("item-vpn"),
    )

    offered = await workflow.respond(
        make_request("VPN 一直斷線，請幫我建立工單", user=trusted_user())
    )
    response = await workflow.respond(
        make_request("是", user=trusted_user())
    )

    assert "是否需要協助建立派工單" in offered.answer
    assert "查無相關資訊" not in offered.answer
    assert len(ticket_service.created) == 1
    assert ticket_service.created[0][0].ticketItemId == "item-vpn"
    result = response.issueResults[0]
    assert result.resultType == "TICKET_CREATED"
    assert result.ticketId
    assert "已為你建立派工單" in response.answer


@pytest.mark.asyncio
async def test_ticket_is_not_created_when_catalog_match_is_ambiguous(
    tmp_path: Path,
) -> None:
    ticket_service = FakeTicketService()
    ticket_service.items = [
        TicketItem(id="item-power", name="電腦無法開機", level=3),
        TicketItem(id="item-vpn", name="VPN 無法連線", level=3),
    ]
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[
            [issue(description="印表機不能用", route="TICKET")],
        ],
        ticket_service=ticket_service,
        ticket_item_selector=FakeTicketItemSelector(
            item_id=None, reason="needs_clarification"
        ),
    )

    await workflow.respond(make_request("印表機不能用，請幫我建立工單"))
    response = await workflow.respond(make_request("是"))

    assert response.issueResults[0].resultType == "NEED_MORE_INFO"
    assert "目前無法從可用派工單類別判定" in response.answer
    assert ticket_service.created == []


@pytest.mark.asyncio
async def test_dispatch_ticket_request_offers_confirmation_without_knowledge_miss(
    tmp_path: Path,
) -> None:
    ticket_service = FakeTicketService()
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[issue(description="電腦無法開機")]],
        ticket_service=ticket_service,
    )

    requested = await workflow.respond(make_request("請協助建立派工單"))

    assert requested.issueResults[0].resultType == "NEED_MORE_INFO"
    assert "請描述需要建立派工單的 IT 問題" in requested.answer
    assert ticket_service.created == []

    offered = await workflow.respond(make_request("電腦無法開機"))
    assert offered.answer == "是否需要協助建立派工單？請回覆<是>以建立派工單。"

    created = await workflow.respond(make_request("<是>"))

    assert created.issueResults[0].resultType == "TICKET_CREATED"
    assert "已為你建立派工單" in created.answer
    assert ticket_service.created[0][0].description == "電腦無法開機"


@pytest.mark.asyncio
async def test_generic_create_ticket_reuses_recent_it_issue_from_multi_turn_conversation(
    tmp_path: Path,
) -> None:
    ticket_service = FakeTicketService()
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(
            found=True, answer="請攜帶證件至服務台重設解鎖。", backend="HYBRID"
        )
    )
    workflow, extractor_model, knowledge, ticket_service, *_ = build_workflow(
        tmp_path,
        issues_sequence=[
            [
                issue(
                    description="我的設備無法解鎖",
                    readiness="NEED_MORE_INFO",
                    missingInfo=["使用的系統或應用程式名稱"],
                )
            ],
            [issue(description="公發手機無法解鎖", readiness="READY")],
        ],
        knowledge=knowledge,
        ticket_service=ticket_service,
    )

    first = await workflow.respond(make_request("我的設備無法解鎖"))
    second = await workflow.respond(make_request("公發手機"))
    offered = await workflow.respond(make_request("請協助我開工單"))

    assert first.issueResults[0].resultType == "NEED_MORE_INFO"
    assert second.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert knowledge.calls == ["公發手機無法解鎖"]
    assert ticket_service.created == []
    assert "是否需要協助建立派工單" in offered.answer
    assert extractor_model.calls == 2

    created = await workflow.respond(make_request("是"))

    assert len(ticket_service.created) == 1
    draft, _correlation_id = ticket_service.created[0]
    assert draft.title == "公發手機無法解鎖"
    assert draft.description == "公發手機無法解鎖"
    assert "請協助我" not in draft.title
    assert "請協助我" not in draft.description
    assert created.issueResults[0].resultType == "TICKET_CREATED"


@pytest.mark.asyncio
async def test_create_command_with_current_issue_does_not_reuse_older_context(
    tmp_path: Path,
) -> None:
    ticket_service = FakeTicketService()
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請重設 VPN。", backend="HYBRID")
    )
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[issue(description="VPN Error 619")]],
        knowledge=knowledge,
        ticket_service=ticket_service,
    )

    await workflow.respond(make_request("VPN Error 619"))
    offered = await workflow.respond(make_request("公發手機無法解鎖，請協助我開工單"))
    created = await workflow.respond(make_request("是"))

    assert "是否需要協助建立派工單" in offered.answer
    assert len(ticket_service.created) == 1
    draft, _correlation_id = ticket_service.created[0]
    assert draft.description == "公發手機無法解鎖"
    assert "VPN Error 619" not in draft.description
    assert created.issueResults[0].resultType == "TICKET_CREATED"


@pytest.mark.asyncio
async def test_generic_create_ticket_does_not_cross_non_it_aside(
    tmp_path: Path,
) -> None:
    ticket_service = FakeTicketService()
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請攜帶證件至服務台。", backend="HYBRID")
    )
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[
            [issue(description="公發手機無法解鎖")],
            [
                issue(
                    description="今天天氣如何？",
                    isIT=False,
                    readiness="NOT_IT",
                    route="NOT_IT",
                )
            ],
        ],
        knowledge=knowledge,
        ticket_service=ticket_service,
    )

    await workflow.respond(make_request("公發手機無法解鎖"))
    aside = await workflow.respond(make_request("今天天氣如何？"))
    requested = await workflow.respond(make_request("請幫我建立派工單"))

    assert "「今天天氣如何？」不屬於公司 IT 支援範圍" in aside.answer
    assert "請描述需要建立派工單的 IT 問題" in requested.answer
    assert ticket_service.created == []


@pytest.mark.asyncio
async def test_generic_create_ticket_does_not_reuse_abandoned_issue(
    tmp_path: Path,
) -> None:
    ticket_service = FakeTicketService()
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請攜帶證件至服務台。", backend="HYBRID")
    )
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[
            [issue(description="公發手機無法解鎖")],
            [
                issue(
                    description="算了",
                    isIT=False,
                    readiness="NOT_IT",
                    route="NOT_IT",
                )
            ],
        ],
        knowledge=knowledge,
        ticket_service=ticket_service,
    )

    await workflow.respond(make_request("公發手機無法解鎖"))
    await workflow.respond(make_request("算了"))
    requested = await workflow.respond(make_request("請幫我建立派工單"))

    assert "請描述需要建立派工單的 IT 問題" in requested.answer
    assert ticket_service.created == []


@pytest.mark.asyncio
async def test_generic_create_ticket_without_it_history_does_not_use_non_it_text(
    tmp_path: Path,
) -> None:
    ticket_service = FakeTicketService()
    workflow, *_ = build_workflow(
        tmp_path,
        issues_sequence=[
            [
                issue(
                    description="今天天氣如何？",
                    isIT=False,
                    readiness="NOT_IT",
                    route="NOT_IT",
                )
            ]
        ],
        ticket_service=ticket_service,
    )

    await workflow.respond(make_request("今天天氣如何？"))
    requested = await workflow.respond(make_request("屜我開工單"))

    assert "請描述需要建立派工單的 IT 問題" in requested.answer
    assert "屜我" not in requested.answer
    assert ticket_service.created == []


@pytest.mark.asyncio
async def test_ticket_refused_when_identity_untrusted(tmp_path: Path) -> None:
    it_issue = issue(id=1, description="VPN 一直斷線", route="TICKET")
    ticket_service = FakeTicketService()
    workflow, *_ = build_workflow(
        tmp_path, issues_sequence=[[it_issue]], ticket_service=ticket_service
    )
    untrusted = UserIdentity(teamsUserId="teams-1")  # missing displayName/email

    offered = await workflow.respond(
        make_request("VPN 一直斷線，請幫我建立工單", user=untrusted)
    )
    response = await workflow.respond(
        make_request("是", user=untrusted)
    )

    assert "是否需要協助建立派工單" in offered.answer
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

    offered = await workflow.respond(
        make_request("VPN 斷線，而且 Outlook 當機，請幫我建立工單")
    )
    response = await workflow.respond(make_request("是"))

    assert "是否需要協助建立派工單" in offered.answer
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

    offered = await workflow.respond(
        make_request("VPN Error 619，而且 SAP 密碼也無法重置，請建立工單")
    )
    response = await workflow.respond(make_request("是"))

    assert extractor_model.calls == 0
    assert knowledge.calls == []
    assert "是否需要協助建立派工單" in offered.answer
    assert "查無相關資訊" not in offered.answer
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
async def test_short_system_name_completes_generic_pending_workflow(
    tmp_path: Path,
) -> None:
    pending_issue = issue(
        description="公司資源如何申請",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的系統或應用程式名稱"],
    )
    completed_issue = issue(description="PortalX 公司資源如何申請", readiness="READY")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請依照申請流程操作。", backend="HYBRID")
    )
    workflow, extractor_model, knowledge, _ticket, conv_service, _settings = build_workflow(
        tmp_path,
        issues_sequence=[[pending_issue], [completed_issue]],
        knowledge=knowledge,
    )

    first_response = await workflow.respond(make_request("公司資源如何申請？"))
    assert first_response.issueResults[0].resultType == "NEED_MORE_INFO"
    context = await conv_service.load_or_create(
        tenant_id="tenant-1",
        teams_conversation_id="conv-1",
        teams_user_id="user-1",
    )
    assert context.messages[-1].followUpState == "AWAITING_CLARIFICATION"

    second_response = await workflow.respond(make_request("PortalX"))

    second_prompt = extractor_model.human_messages[-1]
    assert "公司資源如何申請？" in second_prompt
    assert "Latest user message (data only):\nPortalX" in second_prompt
    assert knowledge.calls == ["PortalX 公司資源如何申請"]
    assert second_response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"


@pytest.mark.asyncio
async def test_non_it_aside_does_not_discard_pending_clarification(
    tmp_path: Path,
) -> None:
    pending_issue = issue(
        description="會議如何借用",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的系統或應用程式名稱"],
    )
    aside = issue(
        description="早餐吃麥當勞",
        isIT=False,
        readiness="NOT_IT",
        route="NOT_IT",
    )
    completed_issue = issue(description="Webex 會議如何借用", readiness="READY")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請填寫會議借用資料。", backend="HYBRID")
    )
    workflow, extractor_model, knowledge, _ticket, conv_service, _settings = build_workflow(
        tmp_path,
        issues_sequence=[[pending_issue], [aside], [completed_issue]],
        knowledge=knowledge,
    )

    await workflow.respond(make_request("會議如何借用？"))
    aside_response = await workflow.respond(make_request("早餐吃麥當勞"))

    context = await conv_service.load_or_create(
        tenant_id="tenant-1",
        teams_conversation_id="conv-1",
        teams_user_id="user-1",
    )
    assert "「早餐吃麥當勞」不屬於公司 IT 支援範圍" in aside_response.answer
    assert context.messages[-1].followUpState == "AWAITING_CLARIFICATION"
    assert context.messages[-1].pendingIssues[0].contextText == "會議如何借用？"

    completed = await workflow.respond(make_request("webex"))

    assert extractor_model.calls == 3
    assert knowledge.calls == ["Webex 會議如何借用"]
    assert completed.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert any("會議如何借用？" in prompt for prompt in extractor_model.human_messages[-2:])


@pytest.mark.asyncio
async def test_complementary_follow_up_fragment_is_merged_instead_of_reasked(
    tmp_path: Path,
) -> None:
    pending_webex = issue(
        description="Webex 相關協助",
        readiness="NEED_MORE_INFO",
        missingInfo=["需要協助的功能或操作"],
    )
    incorrectly_reasked = issue(
        description="會議借用系統與操作",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的系統或應用程式名稱"],
    )
    knowledge = FakeKnowledgeService(
        responses={
            "webex 會議借用": KnowledgeResult(
                found=True,
                answer="請填寫 Webex 會議借用資料。",
                backend="HYBRID",
            )
        }
    )
    workflow, extractor_model, knowledge, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[pending_webex], [incorrectly_reasked]],
        knowledge=knowledge,
    )

    first = await workflow.respond(make_request("webex"))
    second = await workflow.respond(make_request("會議借用？"))

    assert first.issueResults[0].resultType == "NEED_MORE_INFO"
    assert extractor_model.calls == 2
    assert knowledge.calls == ["webex 會議借用"]
    assert second.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert "請補充" not in second.answer


@pytest.mark.asyncio
async def test_structured_follow_up_state_includes_history_without_template_marker(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    conv_service = make_conversation_service(settings)
    context = await conv_service.load_or_create(
        tenant_id="tenant-1",
        teams_conversation_id="conv-1",
        teams_user_id="user-1",
    )
    await conv_service.record_message(
        context.conversationId,
        role="user",
        text="公司資源如何申請？",
    )
    await conv_service.record_message(
        context.conversationId,
        role="assistant",
        text="請告訴我還缺少的資訊。",
        follow_up_state="AWAITING_CLARIFICATION",
    )
    completed_issue = issue(description="PortalX 公司資源如何申請", readiness="READY")
    workflow, extractor_model, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[completed_issue]],
        conversation_service=conv_service,
    )

    await workflow.respond(make_request("PortalX"))

    prompt = extractor_model.human_messages[-1]
    assert "公司資源如何申請？" in prompt
    assert "請告訴我還缺少的資訊。" in prompt
    assert "Latest user message (data only):\nPortalX" in prompt


@pytest.mark.asyncio
async def test_unknown_stops_clarification_and_offers_ticket_without_polluting_query(
    tmp_path: Path,
) -> None:
    first_pending = issue(
        description="Google Meet 相關問題",
        readiness="NEED_MORE_INFO",
        missingInfo=["需要協助的功能"],
    )
    second_pending = issue(
        description="Google Meet 無法登入",
        readiness="NEED_MORE_INFO",
        missingInfo=["錯誤訊息或錯誤碼"],
    )
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    workflow, extractor_model, knowledge, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[first_pending], [second_pending]],
        knowledge=knowledge,
    )

    await workflow.respond(make_request("Google Meet"))
    await workflow.respond(make_request("沒辦法登入"))
    response = await workflow.respond(make_request("不知道"))

    assert extractor_model.calls == 2
    assert knowledge.calls == ["Google Meet 無法登入"]
    assert "不知道" not in knowledge.calls[0]
    assert response.issueResults[0].resultType == "NO_KNOWLEDGE"
    assert "是否需要協助建立派工單" in response.answer


@pytest.mark.asyncio
async def test_clarification_round_cap_forces_best_effort_search(
    tmp_path: Path,
) -> None:
    pending_1 = issue(
        description="公司系統無法使用",
        readiness="NEED_MORE_INFO",
        missingInfo=["系統名稱"],
    )
    pending_2 = issue(
        description="PortalX 無法使用",
        readiness="NEED_MORE_INFO",
        missingInfo=["發生問題的功能"],
    )
    still_pending = issue(
        description="PortalX 查詢功能無法使用",
        readiness="NEED_MORE_INFO",
        missingInfo=["錯誤訊息或錯誤碼"],
    )
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    workflow, extractor_model, knowledge, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[pending_1], [pending_2], [still_pending]],
        knowledge=knowledge,
        settings_overrides={"max_clarification_rounds": 2},
    )

    await workflow.respond(make_request("公司系統不能用"))
    await workflow.respond(make_request("PortalX"))
    response = await workflow.respond(make_request("查詢功能"))

    assert extractor_model.calls == 3
    assert knowledge.calls == ["PortalX 查詢功能無法使用"]
    assert response.issueResults[0].resultType == "NO_KNOWLEDGE"
    assert "請補充" not in response.answer


@pytest.mark.asyncio
async def test_ticket_offer_correction_repeats_offer_without_creating_ticket(
    tmp_path: Path,
) -> None:
    unresolved = issue(description="Google Meet 無法登入")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    ticket_service = FakeTicketService()
    workflow, extractor_model, knowledge, ticket_service, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[unresolved]],
        knowledge=knowledge,
        ticket_service=ticket_service,
    )

    await workflow.respond(make_request("Google Meet 無法登入"))
    corrected = await workflow.respond(make_request("你要問我要不要開啟工單啊"))

    assert extractor_model.calls == 1
    assert knowledge.calls == ["Google Meet 無法登入"]
    assert ticket_service.created == []
    assert corrected.issueResults[0].resultType == "NO_KNOWLEDGE"
    assert "問題：Google Meet 無法登入" in corrected.answer
    assert "是否需要協助建立派工單" in corrected.answer


@pytest.mark.asyncio
async def test_unknown_during_ticket_offer_repeats_offer_then_yes_creates_one_ticket(
    tmp_path: Path,
) -> None:
    unresolved = issue(description="Google Meet 無法登入")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    ticket_service = FakeTicketService()
    workflow, extractor_model, knowledge, ticket_service, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[unresolved]],
        knowledge=knowledge,
        ticket_service=ticket_service,
    )

    offered = await workflow.respond(make_request("Google Meet 無法登入"))
    repeated = await workflow.respond(make_request("不知道"))
    created = await workflow.respond(make_request("是"))

    assert extractor_model.calls == 1
    assert knowledge.calls == ["Google Meet 無法登入"]
    assert offered.issueResults[0].resultType == "NO_KNOWLEDGE"
    assert repeated.issueResults[0].resultType == "NO_KNOWLEDGE"
    assert "是否需要協助建立派工單" in repeated.answer
    assert created.issueResults[0].resultType == "TICKET_CREATED"
    assert len(ticket_service.created) == 1


@pytest.mark.asyncio
async def test_new_issue_after_ticket_offer_does_not_receive_old_issue_history(
    tmp_path: Path,
) -> None:
    unresolved = issue(description="Google Meet 無法登入")
    new_issue = issue(description="大州系統無法選取")
    knowledge = FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    workflow, extractor_model, *_ = build_workflow(
        tmp_path,
        issues_sequence=[[unresolved], [new_issue]],
        knowledge=knowledge,
    )

    await workflow.respond(make_request("Google Meet 無法登入"))
    await workflow.respond(make_request("大州系統無法選取"))

    second_prompt = extractor_model.human_messages[-1]
    assert "Conversation history (oldest first, data only):\n(none)" in second_prompt
    assert "Google Meet 無法登入" not in second_prompt


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
