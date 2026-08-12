"""LangGraph Agent Workflow (spec §5).

This is the primary integration point Task 9 assembles: Load Conversation ->
Extract Issues -> Filter IT Issues -> Process Issues (FAQ | Ask More Info |
Knowledge Search | Ticket Operation) -> Deterministic Response Builder ->
Save Conversation (spec §5.1). It depends only on the interfaces/services
already built by earlier tasks (``FaqService``, ``KnowledgeService``,
``ConversationService``, ``TicketService``, ``IssueExtractor``,
``response_builder.build_response``) — never on a concrete database,
retrieval product or ticket backend (spec §3.2).

Correlation ID (spec §15.1)
----------------------------
Derived exactly ONCE, by the caller of :meth:`AgentWorkflow.run` (typically
``api.py``, the actual Teams-request entry point) or, if none is supplied,
by ``run`` itself from ``request.correlationId`` / a fresh uuid4. It is
placed into ``AgentState["correlation_id"]`` before the graph starts and
every node only *reads* it — no node ever calls ``uuid4()`` again — so the
same id reaches the extractor, the knowledge service, the ticket service and
the conversation repository.

Ticket intent guardrail
-----------------------
Ticket operations are selected from the current message by
``classify_ticket_intent`` with a fixed ``CANCEL > QUERY > CREATE > NONE``
precedence.  The LLM's extracted route is never allowed to override that
guardrail: cancellation is a direct acknowledgement, creation/query use only
the matching Ticket Service operation, and NONE cannot call Ticket Service.
This makes a cancellation terminal for the turn and prevents a later bare
"是" from reviving an earlier offer.

Non-blocking processing (spec §4.2)
--------------------------------------
Every IT issue is processed concurrently via ``asyncio.gather(...,
return_exceptions=True)``, wrapped in a per-issue try/except besides. One
issue's exception becomes a ``FAILED`` IssueResult (with the error kept out
of the user-facing text — response_builder never renders
``IssueResult.error``) and never stops the others.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .confirmation import (
    TicketIntent,
    classify_ticket_intent,
    is_pending_ticket_offer_confirmation,
)
from .contracts import (
    AgentImage,
    AgentRequest,
    AgentResponse,
    Citation,
    ConversationContext,
    Issue,
    IssueResult,
    PendingIssueContext,
    TicketDraft,
    UserContext,
)
from .conversation import ConversationService
from .extractor import IssueExtractor, merge_pending_ticket_issues
from .faq import FaqService
from .graph import user_context_from_identity
from .knowledge import KnowledgeService, LlmCallCounter
from .response_builder import build_response
from .retrieval import HybridIndex
from .settings import RagSettings
from .ticket import (
    TicketService,
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
    UntrustedRequesterError,
)

logger = logging.getLogger(__name__)

# This marker remains solely for deciding whether the extractor should see a
# no-knowledge offer as recent context.  It is not an authorization to create
# a ticket; ticket actions are always determined from the current turn.
_TICKET_OFFER_MARKER = "是否需要協助建立工單"

# Progress stages surfaced to the Teams user while the graph runs (spec §5.1
# node boundaries, reused as user-visible progress).
#
# The mapping is keyed by the node that just FINISHED and names the work that
# is now starting, because `graph.astream` emits an update only once a node
# completes. `save_conversation` is deliberately absent: by the time it runs
# the answer is already known, and the Teams Adapter finalizes the streamed
# message rather than showing another status line.
#
# These are the only user-visible strings in this module. Everything else the
# user reads is rendered by `response_builder`.
STAGE_LABELS: dict[str, str] = {
    "load_conversation": "正在理解你的問題…",
    "extract_issues": "正在確認問題類型…",
    "filter_it_issues": "正在檢索知識庫…",
    "process_issues": "正在整理答案…",
}
# Sent before the graph starts, so the user sees something within one Teams
# round-trip rather than waiting for the first node to finish.
INITIAL_STAGE_LABEL = "已收到你的問題…"


class AgentState(TypedDict, total=False):
    """Workflow state (spec §5.2), plus a few documented workflow-only fields.

    Spec-mandated fields: ``request``, ``correlation_id``, ``user``,
    ``conversation``, ``issues``, ``issue_results``, ``final_response``.

    Added fields (all workflow-internal plumbing, never part of the spec's
    literal state shape, but needed to keep node functions pure/composable):

    - ``it_issues``: the IT-only subset of ``issues`` computed by the
      "Filter IT Issues" node, so "Process Issues" doesn't recompute it and
      the node boundary from the spec diagram (§5.1) is real, not just a
      naming convention.
    - ``too_many_issues``: propagated from the Issue Extractor (spec §4.2)
      so the Response Builder can render the "please prioritize" notice.
    - ``llm_call_counter``: a single ``LlmCallCounter`` (from ``knowledge.py``)
      shared across the extractor's own call count and every Knowledge
      Service call made while processing issues, so spec §16's
      ``MAX_LLM_CALLS_PER_REQUEST`` is enforced per-*request*, not
      per-component.
    - ``citations`` / ``images`` / ``feedback_enabled``: the rest of what
      the deterministic Response Builder produces (``final_response`` only
      covers the rendered text; ``AgentResponse`` needs the rest too).
    """

    request: AgentRequest
    correlation_id: str
    user: UserContext
    conversation: ConversationContext
    issues: list[Issue]
    it_issues: list[Issue]
    issue_results: list[IssueResult]
    too_many_issues: bool
    llm_call_counter: LlmCallCounter
    final_response: str
    citations: list[Citation]
    images: list[AgentImage]
    feedback_enabled: bool
    ticket_intent: TicketIntent
    prior_pending_issues: list[PendingIssueContext]
    force_ticket_offer: bool


def _has_pending_ticket_offer(conversation: ConversationContext) -> bool:
    if not conversation.messages:
        return False
    last = conversation.messages[-1]
    if last.role != "assistant":
        return False
    if last.followUpState == "AWAITING_TICKET_CONFIRMATION":
        return True
    # Backward compatibility for conversations saved before followUpState
    # existed. Newly written messages use the structured state above.
    return _TICKET_OFFER_MARKER in last.text


def _pending_offer_issues(conversation: ConversationContext) -> list[Issue]:
    """Recover the exact issue labels rendered in the live assistant offer."""
    if not _has_pending_ticket_offer(conversation):
        return []
    last = conversation.messages[-1]
    if last.pendingIssues:
        return [
            Issue(
                id=index,
                description=pending.description,
                isIT=True,
                readiness="READY",
                missingInfo=[],
                route="TICKET",
                faqKey=None,
                ticketAction=None,
            )
            for index, pending in enumerate(last.pendingIssues, start=1)
        ]
    descriptions = [
        line.removeprefix("問題：").strip()
        for line in last.text.splitlines()
        if line.startswith("問題：") and line.removeprefix("問題：").strip()
    ]
    return [
        Issue(
            id=index,
            description=description,
            isIT=True,
            readiness="READY",
            missingInfo=[],
            route="TICKET",
            faqKey=None,
            ticketAction=None,
        )
        for index, description in enumerate(descriptions, start=1)
    ]


def _pending_clarifications(
    conversation: ConversationContext,
) -> list[PendingIssueContext]:
    if not conversation.messages:
        return []
    last = conversation.messages[-1]
    if (
        last.role == "assistant"
        and last.followUpState == "AWAITING_CLARIFICATION"
    ):
        return list(last.pendingIssues)
    return []


def _unable_to_provide_detail(text: str) -> bool:
    """Recognise a short answer that cannot satisfy a pending clarification."""
    normalized = text.strip().lower().rstrip("。.!！?？")
    if not normalized or len(normalized) > 24:
        return False
    exact = {
        "不知道",
        "不清楚",
        "不確定",
        "不曉得",
        "沒有",
        "看不懂",
        "無法確認",
        "不知道欸",
        "不知道耶",
    }
    prefixes = ("沒有看到", "沒有顯示", "找不到", "無法提供")
    return normalized in exact or normalized.startswith(prefixes)


def _abandons_pending_issue(text: str) -> bool:
    """Recognise an explicit request to stop or switch away from a follow-up."""
    normalized = text.strip().lower().rstrip("。.!！?？")
    markers = (
        "不問了",
        "算了",
        "取消",
        "不用了",
        "先不用",
        "換個問題",
        "換一題",
        "另外一個問題",
    )
    return any(marker in normalized for marker in markers)


def _compose_pending_description(pending: PendingIssueContext, detail: str) -> str:
    """Join complementary user fragments into one stable retrieval query."""
    base = (pending.contextText or pending.description).strip().rstrip("。.!！?？")
    addition = detail.strip().rstrip("。.!！?？")
    if not base:
        return addition
    if not addition or addition.lower() in base.lower():
        return base
    return f"{base} {addition}"


def _missing_info_kind(question: str) -> str | None:
    normalized = question.lower()
    if any(term in normalized for term in ("系統", "應用程式", "app", "軟體", "平台", "用戶端")):
        return "SYSTEM"
    if any(term in normalized for term in ("錯誤訊息", "錯誤碼", "error", "代碼")):
        return "ERROR"
    if any(term in normalized for term in ("功能", "操作", "需求", "要做什麼", "協助項目")):
        return "FEATURE"
    return None


def _detail_satisfies_kind(text: str, kind: str) -> bool:
    normalized = text.strip().lower().rstrip("。.!！?？")
    if not normalized:
        return False
    if kind == "ERROR":
        return bool(
            any(term in normalized for term in ("錯誤", "error", "失敗", "異常"))
            or any(character.isdigit() for character in normalized)
        )
    if kind == "FEATURE":
        return any(
            term in normalized
            for term in (
                "借用",
                "預約",
                "申請",
                "登入",
                "連線",
                "上傳",
                "下載",
                "安裝",
                "開啟",
                "列印",
                "查詢",
                "重置",
                "變更",
                "設定",
            )
        )
    if kind == "SYSTEM":
        if len(normalized) > 40:
            return False
        # Product-only fragments normally contain Latin letters (Webex,
        # SAP, PortalX) or a short Chinese proper name.  Problem/action words
        # indicate that this is likely a complete issue rather than a name.
        issue_markers = (
            "無法",
            "不能",
            "壞",
            "問題",
            "怎麼",
            "如何",
            "借用",
            "登入",
            "連線",
            "申請",
            "錯誤",
            "error",
        )
        return not any(marker in normalized for marker in issue_markers)
    return False


def _answers_missing_info(text: str, questions: list[str]) -> bool:
    return any(
        kind is not None and _detail_satisfies_kind(text, kind)
        for question in questions
        if (kind := _missing_info_kind(question)) is not None
    )


def _complete_complementary_pending_issue(
    issues: list[Issue],
    pending_issues: list[PendingIssueContext],
    latest_text: str,
) -> list[Issue]:
    """Resolve two complementary fragments instead of asking in a loop.

    The extractor has already decided that the latest message is IT-related.
    If one active clarification exists and the extractor still wants to ask a
    different clarification, conversationally the short latest turn is the
    answer to the outstanding slot.  Compose both user fragments and proceed
    with a best-effort lookup.  Clearly non-IT turns never enter this path and
    explicit topic abandonment is handled separately.
    """
    if (
        len(pending_issues) != 1
        or len(issues) != 1
        or _abandons_pending_issue(latest_text)
    ):
        return issues
    pending = pending_issues[0]
    current = issues[0]
    if (
        not current.isIT
        or current.readiness != "NEED_MORE_INFO"
        or not pending.missingInfo
        or not _answers_missing_info(latest_text, pending.missingInfo)
        or not _answers_missing_info(
            pending.contextText or pending.description, current.missingInfo
        )
    ):
        return issues
    return [
        current.model_copy(
            update={
                "description": _compose_pending_description(pending, latest_text),
                "readiness": "READY",
                "missingInfo": [],
                "route": pending.route if pending.route != "NOT_IT" else "KNOWLEDGE",
                "faqKey": pending.faqKey,
            }
        )
    ]


def _preserves_interrupted_clarification(state: AgentState) -> bool:
    """Keep an unresolved IT question alive across a harmless non-IT aside."""
    prior = state.get("prior_pending_issues", [])
    issues = state.get("issues", [])
    request = state.get("request")
    return bool(
        prior
        and issues
        and all(not issue.isIT for issue in issues)
        and request is not None
        and not _abandons_pending_issue(request.message.text)
    )


def _requests_ticket_offer(text: str) -> bool:
    """Detect a request to present the ticket option, without creating one."""
    normalized = text.strip()
    if "工單" not in normalized:
        return False
    markers = (
        "要不要",
        "是否",
        "問我",
        "問問",
        "你要問",
        "你應該問",
        "怎麼沒問",
        "沒有問",
        "沒問",
    )
    return any(marker in normalized for marker in markers)


def _pending_context_to_ready_issue(
    pending: PendingIssueContext, *, issue_id: int
) -> Issue:
    return Issue(
        id=issue_id,
        description=pending.description,
        isIT=True,
        readiness="READY",
        missingInfo=[],
        route=pending.route if pending.route != "NOT_IT" else "KNOWLEDGE",
        faqKey=pending.faqKey,
        ticketAction=None,
    )


def _recent_unresolved_contexts(
    conversation: ConversationContext,
) -> list[PendingIssueContext]:
    for message in reversed(conversation.messages):
        if message.role != "assistant":
            continue
        if message.pendingIssues:
            return list(message.pendingIssues)
        if "目前企業知識庫中查無相關資訊" not in message.text:
            continue
        descriptions = [
            line.removeprefix("問題：").strip()
            for line in message.text.splitlines()
            if line.startswith("問題：") and line.removeprefix("問題：").strip()
        ]
        if descriptions:
            return [
                PendingIssueContext(description=description)
                for description in descriptions
            ]
    return []


def _needs_history_for_follow_up(conversation: ConversationContext) -> bool:
    """Only expose prior turns when the assistant is awaiting a reply.

    Passing every resolved topic to the extractor makes a complete new issue
    vulnerable to being merged with the previous one (for example, a VPN
    question followed by an unrelated 大州 question). New messages therefore
    carry an explicit structured follow-up state instead of relying on the
    wording of the rendered assistant response.
    """
    if not conversation.messages:
        return False
    last = conversation.messages[-1]
    if last.role != "assistant":
        return False
    if last.followUpState in {
        "AWAITING_CLARIFICATION",
    }:
        return True
    # Backward compatibility for active conversations written by an older
    # revision. This fallback can be removed after the retention window.
    return "請補充：" in last.text


def _knowledge_search_supports_call_counter(knowledge_service: KnowledgeService) -> bool:
    try:
        signature = inspect.signature(knowledge_service.search)
    except (TypeError, ValueError):  # pragma: no cover - defensive only
        return False
    return "call_counter" in signature.parameters


def build_knowledge_service(
    settings: RagSettings,
    index: HybridIndex,
    model=None,
) -> KnowledgeService:
    """Single factory honoring ``settings.knowledge_service_mode`` (spec §8.2/§8.3).

    This is the ONE place the mode switch lives; nothing else in the
    workflow (or ``api.py``) branches on ``knowledge_service_mode``.
    """
    from .knowledge import HybridKnowledgeService

    if settings.knowledge_service_mode == "GEMINI_FILE_SEARCH":
        from .file_search_registry import FileSearchDocumentRegistry
        from .gemini_file_search import GeminiFileSearchKnowledgeService

        logger.warning(
            "KNOWLEDGE_SERVICE_MODE=GEMINI_FILE_SEARCH selected; this is a "
            "spike-only adapter, not the validated default (spec §8.3)."
        )
        return GeminiFileSearchKnowledgeService(
            api_key=None,
            file_search_store=settings.gemini_file_search_store or "",
            model=settings.gemini_file_search_model,
            top_k=settings.top_k,
            registry=FileSearchDocumentRegistry.from_chunks(index.chunks),
            max_images=settings.max_images,
            enforce_acl=settings.gemini_file_search_enforce_acl,
        )
    return HybridKnowledgeService(settings, index, model)


class AgentWorkflow:
    """LangGraph workflow implementing spec §5.1's node pipeline."""

    def __init__(
        self,
        settings: RagSettings,
        *,
        extractor: IssueExtractor,
        faq_service: FaqService,
        knowledge_service: KnowledgeService,
        conversation_service: ConversationService,
        ticket_service: TicketService,
    ) -> None:
        self.settings = settings
        self.extractor = extractor
        self.faq_service = faq_service
        self.knowledge_service = knowledge_service
        self.conversation_service = conversation_service
        self.ticket_service = ticket_service
        self._knowledge_supports_counter = _knowledge_search_supports_call_counter(
            knowledge_service
        )
        self.graph = self._build_graph()

    # --- graph wiring ----------------------------------------------

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("load_conversation", self._load_conversation)
        builder.add_node("extract_issues", self._extract_issues)
        builder.add_node("filter_it_issues", self._filter_it_issues)
        builder.add_node("process_issues", self._process_issues)
        builder.add_node("build_response", self._build_response)
        builder.add_node("save_conversation", self._save_conversation)

        builder.add_edge(START, "load_conversation")
        builder.add_edge("load_conversation", "extract_issues")
        builder.add_edge("extract_issues", "filter_it_issues")
        builder.add_edge("filter_it_issues", "process_issues")
        builder.add_edge("process_issues", "build_response")
        builder.add_edge("build_response", "save_conversation")
        builder.add_edge("save_conversation", END)
        return builder.compile()

    # --- nodes -------------------------------------------------------

    async def _load_conversation(self, state: AgentState) -> dict:
        request = state["request"]
        user = user_context_from_identity(request.user)
        teams_conversation_id = (
            request.conversation.conversationId or f"req:{request.requestId}"
        )
        teams_user_id = (
            request.user.teamsUserId or request.user.entraObjectId or "anonymous"
        )
        conversation = await self.conversation_service.load_or_create(
            tenant_id=request.conversation.tenantId,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
        )
        return {"user": user, "conversation": conversation}

    async def _extract_issues(self, state: AgentState) -> dict:
        request = state["request"]
        correlation_id = state["correlation_id"]
        conversation = state["conversation"]
        ticket_intent = classify_ticket_intent(request.message.text)
        prior_pending_issues = _pending_clarifications(conversation)
        force_ticket_offer = False
        pending_confirmation = False
        if (
            ticket_intent == TicketIntent.NONE
            and _has_pending_ticket_offer(conversation)
            and is_pending_ticket_offer_confirmation(request.message.text)
        ):
            ticket_intent = TicketIntent.CREATE
            pending_confirmation = True
        pending_issues = _pending_offer_issues(conversation) if pending_confirmation else []
        active_offer_contexts = (
            _recent_unresolved_contexts(conversation)
            if ticket_intent == TicketIntent.NONE
            and _has_pending_ticket_offer(conversation)
            and _unable_to_provide_detail(request.message.text)
            else []
        )
        requested_offer_contexts = (
            _recent_unresolved_contexts(conversation)
            if ticket_intent == TicketIntent.NONE
            and _requests_ticket_offer(request.message.text)
            else []
        )
        if pending_issues:
            # The extractor may recover several outstanding problems from
            # history. A single confirmation authorizes one combined ticket,
            # never one attempt per recovered issue.
            issues = [merge_pending_ticket_issues(pending_issues)]
            too_many_issues = False
            llm_calls = 0
        elif active_offer_contexts:
            issues = [
                _pending_context_to_ready_issue(pending, issue_id=index)
                for index, pending in enumerate(active_offer_contexts, start=1)
            ]
            too_many_issues = False
            llm_calls = 0
            force_ticket_offer = True
        elif requested_offer_contexts:
            issues = [
                _pending_context_to_ready_issue(pending, issue_id=index)
                for index, pending in enumerate(requested_offer_contexts, start=1)
            ]
            too_many_issues = False
            llm_calls = 0
            force_ticket_offer = True
        elif prior_pending_issues and _unable_to_provide_detail(request.message.text):
            # The user cannot provide the requested detail. Stop interrogating
            # and search with the best complete description accumulated so far;
            # never append the literal word "不知道" to the retrieval query.
            issues = [
                _pending_context_to_ready_issue(pending, issue_id=index)
                for index, pending in enumerate(prior_pending_issues, start=1)
            ]
            too_many_issues = False
            llm_calls = 0
        else:
            history = await self.conversation_service.get_history(
                conversation.conversationId
            )
            if ticket_intent == TicketIntent.CANCEL or not _needs_history_for_follow_up(
                conversation
            ):
                history = []
            faq_keys = self.faq_service.available_keys()
            outcome = await self.extractor.extract(
                text=request.message.text,
                history=history,
                faq_keys=faq_keys,
                correlation_id=correlation_id,
            )
            issues = outcome.issues
            issues = _complete_complementary_pending_issue(
                issues, prior_pending_issues, request.message.text
            )
            too_many_issues = outcome.too_many_issues
            llm_calls = outcome.llm_calls
            previous_count = max(
                (pending.clarificationCount for pending in prior_pending_issues),
                default=0,
            )
            if previous_count >= self.settings.max_clarification_rounds:
                # The extractor may still ask another reasonable question,
                # but the conversation-level cap wins over per-turn output.
                issues = [
                    issue.model_copy(
                        update={"readiness": "READY", "missingInfo": []}
                    )
                    if issue.readiness == "NEED_MORE_INFO"
                    else issue
                    for issue in issues
                ]
        counter = LlmCallCounter(count=llm_calls)
        return {
            "issues": issues,
            "too_many_issues": too_many_issues,
            "llm_call_counter": counter,
            "ticket_intent": ticket_intent,
            "prior_pending_issues": prior_pending_issues,
            "force_ticket_offer": force_ticket_offer,
        }

    async def _filter_it_issues(self, state: AgentState) -> dict:
        it_issues = [issue for issue in state.get("issues", []) if issue.isIT]
        return {"it_issues": it_issues}

    async def _process_issues(self, state: AgentState) -> dict:
        correlation_id = state["correlation_id"]
        user = state["user"]
        counter = state["llm_call_counter"]
        it_issues = state.get("it_issues", [])
        ticket_intent = state.get("ticket_intent", TicketIntent.NONE)

        lock = asyncio.Lock()
        ticket_created = {"done": False}

        async def handle(issue: Issue) -> IssueResult:
            try:
                if state.get("force_ticket_offer", False):
                    return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE")
                return await self._handle_issue(
                    issue,
                    user=user,
                    correlation_id=correlation_id,
                    counter=counter,
                    lock=lock,
                    ticket_created=ticket_created,
                    ticket_intent=ticket_intent,
                )
            except Exception as exc:  # noqa: BLE001 - one issue must never sink the rest
                logger.error(
                    "Issue processing failed: issue_id=%s error_type=%s correlation_id=%s",
                    issue.id,
                    type(exc).__name__,
                    correlation_id,
                )
                return IssueResult(
                    issueId=issue.id,
                    resultType="FAILED",
                    error=f"{type(exc).__name__}: {exc}"[:300],
                )

        gathered = await asyncio.gather(
            *(handle(issue) for issue in it_issues), return_exceptions=True
        )
        issue_results: list[IssueResult] = []
        for issue, outcome in zip(it_issues, gathered, strict=True):
            if isinstance(outcome, BaseException):
                logger.error(
                    "Issue processing raised unexpectedly: issue_id=%s error_type=%s "
                    "correlation_id=%s",
                    issue.id,
                    type(outcome).__name__,
                    correlation_id,
                )
                issue_results.append(
                    IssueResult(
                        issueId=issue.id,
                        resultType="FAILED",
                        error=type(outcome).__name__[:300],
                    )
                )
            else:
                issue_results.append(outcome)
        return {"issue_results": issue_results}

    async def _handle_issue(
        self,
        issue: Issue,
        *,
        user: UserContext,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
        ticket_created: dict,
        ticket_intent: TicketIntent,
    ) -> IssueResult:
        if ticket_intent == TicketIntent.DELETE_DENIED:
            return IssueResult(issueId=issue.id, resultType="TICKET_DELETE_DENIED")

        if ticket_intent == TicketIntent.CANCEL:
            return IssueResult(issueId=issue.id, resultType="TICKET_CANCELLED")

        if ticket_intent in {TicketIntent.CREATE, TicketIntent.QUERY}:
            return await self._handle_ticket(
                issue,
                user=user,
                correlation_id=correlation_id,
                lock=lock,
                ticket_created=ticket_created,
                ticket_intent=ticket_intent,
            )

        if issue.readiness == "NEED_MORE_INFO":
            return IssueResult(
                issueId=issue.id,
                resultType="NEED_MORE_INFO",
                questions=issue.missingInfo,
            )

        if issue.route == "FAQ":
            entry = self.faq_service.get(issue.faqKey) if issue.faqKey else None
            if entry is not None:
                # Spec §7.3: FAQ answer used VERBATIM. No LLM, no rewriting.
                return IssueResult(
                    issueId=issue.id,
                    resultType="FAQ_ANSWERED",
                    answer=entry.answer,
                    backend="FAQ",
                )
            # Miss or disabled entry falls back to KNOWLEDGE, never fails.
            return await self._handle_knowledge(issue, user, correlation_id, counter, lock)

        if issue.route == "KNOWLEDGE":
            return await self._handle_knowledge(issue, user, correlation_id, counter, lock)

        if issue.route == "TICKET":
            # Defense in depth: extractor routes are advisory.  A message
            # with no deterministic ticket intent must not call Ticket API.
            return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE")

        # Defensive fallback: NOT_IT issues are filtered out before this
        # point (Filter IT Issues node), so this should be unreachable.
        return IssueResult(issueId=issue.id, resultType="FAILED", error="unexpected_route")

    async def _handle_knowledge(
        self,
        issue: Issue,
        user: UserContext,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
    ) -> IssueResult:
        async with lock:
            budget_exceeded = counter.count >= self.settings.max_llm_calls_per_request

        if budget_exceeded:
            # Spec §16: stop making further LLM calls and degrade gracefully
            # rather than raising.
            logger.warning(
                "LLM call budget exceeded, degrading issue to NO_KNOWLEDGE: "
                "issue_id=%s correlation_id=%s",
                issue.id,
                correlation_id,
            )
            return IssueResult(
                issueId=issue.id, resultType="NO_KNOWLEDGE", backend="BUDGET_EXCEEDED"
            )

        if self._knowledge_supports_counter:
            result = await self.knowledge_service.search(
                issue.description,
                user,
                correlation_id=correlation_id,
                call_counter=counter,
            )
        else:
            result = await self.knowledge_service.search(
                issue.description, user, correlation_id=correlation_id
            )
            async with lock:
                counter.increment()

        if result.found:
            return IssueResult(
                issueId=issue.id,
                resultType="KNOWLEDGE_ANSWERED",
                answer=result.answer,
                sources=result.sources,
                images=result.images,
                backend=result.backend,
            )
        return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE", backend=result.backend)

    async def _handle_ticket(
        self,
        issue: Issue,
        *,
        user: UserContext,
        correlation_id: str,
        lock: asyncio.Lock,
        ticket_created: dict,
        ticket_intent: TicketIntent,
    ) -> IssueResult:
        if ticket_intent == TicketIntent.QUERY:
            return await self._query_tickets(issue, user, correlation_id)
        if ticket_intent != TicketIntent.CREATE:
            return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE")

        # Spec §11.4: identity must come ONLY from the trusted Teams/Entra
        # context, never from the user's free text.
        if not user.is_trusted_for_ticket:
            logger.warning(
                "Ticket creation refused: untrusted requester identity. "
                "issue_id=%s correlation_id=%s",
                issue.id,
                correlation_id,
            )
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")

        # Spec §11.5: at most one ticket created per turn.
        async with lock:
            if ticket_created["done"]:
                allowed = False
            else:
                ticket_created["done"] = True
                allowed = True
        if not allowed:
            logger.info(
                "Ticket creation skipped: one-ticket-per-turn limit already reached. "
                "issue_id=%s correlation_id=%s",
                issue.id,
                correlation_id,
            )
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_limit_per_turn"
            )

        requester_id = user.entraObjectId or user.teamsUserId or ""
        try:
            items = await self.ticket_service.get_ticket_items(correlation_id=correlation_id)
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        item_id = items[0].id if items else "GENERAL"
        draft = TicketDraft(
            requesterId=requester_id,
            requesterName=user.displayName or "",
            requesterEmail=user.email or "",
            title=issue.description[:120],
            description=issue.description,
            ticketItemId=item_id,
        )
        try:
            ticket = await self.ticket_service.create_ticket(draft, correlation_id=correlation_id)
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except UntrustedRequesterError:
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        sources = [Citation(title=f"{ticket.title} ({ticket.status})", url=ticket.url)]
        return IssueResult(
            issueId=issue.id, resultType="TICKET_CREATED", ticketId=ticket.id, sources=sources
        )

    async def _query_tickets(
        self, issue: Issue, user: UserContext, correlation_id: str
    ) -> IssueResult:
        # Spec §17: never allow querying another user's tickets — always
        # scope strictly to the trusted current-user id.
        requester_id = user.entraObjectId or user.teamsUserId
        if not requester_id:
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")
        try:
            tickets = await self.ticket_service.list_tickets_by_requester(
                requester_id, correlation_id=correlation_id
            )
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        sources = [Citation(title=f"{t.title} ({t.status})", url=t.url) for t in tickets]
        return IssueResult(issueId=issue.id, resultType="TICKET_FOUND", sources=sources)

    async def _build_response(self, state: AgentState) -> dict:
        # Spec §5.3: deterministic template only, no LLM call from here on.
        offer_ticket = self.settings.ticket_service_mode != "DISABLED"
        built = build_response(
            issues=state.get("issues", []),
            results=state.get("issue_results", []),
            too_many_issues=state.get("too_many_issues", False),
            settings=self.settings,
            offer_ticket_on_no_knowledge=offer_ticket,
            correlation_id=state["correlation_id"],
        )
        return {
            "final_response": built.text,
            "citations": built.citations,
            "images": built.images,
            "feedback_enabled": built.feedback_enabled,
        }

    async def _save_conversation(self, state: AgentState) -> dict:
        request = state["request"]
        conversation = state["conversation"]
        correlation_id = state["correlation_id"]
        pending_issues = self._pending_issues_for_next_turn(state)
        await self.conversation_service.record_message(
            conversation.conversationId,
            role="user",
            text=request.message.text,
            correlation_id=correlation_id,
        )
        await self.conversation_service.record_message(
            conversation.conversationId,
            role="assistant",
            text=state.get("final_response", ""),
            correlation_id=correlation_id,
            follow_up_state=self._follow_up_state(state, pending_issues),
            pending_issues=pending_issues,
        )
        return {}

    @staticmethod
    def _pending_issues_for_next_turn(
        state: AgentState,
    ) -> list[PendingIssueContext]:
        issues_by_id = {issue.id: issue for issue in state.get("issues", [])}
        prior = state.get("prior_pending_issues", [])
        previous_count = max(
            (pending.clarificationCount for pending in prior), default=0
        )
        previous_questions = [
            question
            for pending in prior
            for question in pending.askedQuestions
        ]
        pending_contexts: list[PendingIssueContext] = []
        if _preserves_interrupted_clarification(state):
            return list(prior)
        for result in state.get("issue_results", []):
            issue = issues_by_id.get(result.issueId)
            if issue is None:
                continue
            if result.resultType == "NEED_MORE_INFO":
                asked_questions = list(
                    dict.fromkeys([*previous_questions, *result.questions])
                )
                pending_contexts.append(
                    PendingIssueContext(
                        description=issue.description,
                        contextText=(
                            prior[0].contextText
                            if len(prior) == 1 and prior[0].contextText
                            else state["request"].message.text
                        ),
                        route=issue.route,
                        faqKey=issue.faqKey,
                        missingInfo=result.questions,
                        askedQuestions=asked_questions,
                        clarificationCount=previous_count + 1,
                    )
                )
            elif (
                result.resultType == "NO_KNOWLEDGE"
                and _TICKET_OFFER_MARKER in state.get("final_response", "")
            ):
                pending_contexts.append(
                    PendingIssueContext(
                        description=issue.description,
                        route="KNOWLEDGE",
                    )
                )
        return pending_contexts

    @staticmethod
    def _follow_up_state(
        state: AgentState, pending_issues: list[PendingIssueContext]
    ) -> str:
        if any(
            result.resultType == "NEED_MORE_INFO"
            for result in state.get("issue_results", [])
        ):
            return "AWAITING_CLARIFICATION"
        if pending_issues and _preserves_interrupted_clarification(state):
            return "AWAITING_CLARIFICATION"
        if _TICKET_OFFER_MARKER in state.get("final_response", ""):
            return "AWAITING_TICKET_CONFIRMATION"
        return "NONE"

    # --- entry points --------------------------------------------------

    def _initial_state(
        self, request: AgentRequest, correlation_id: str | None
    ) -> AgentState:
        # Spec §15.1: derived exactly once, never regenerated between nodes.
        resolved_correlation_id = correlation_id or request.correlationId or str(uuid.uuid4())
        return {
            "request": request,
            "correlation_id": resolved_correlation_id,
            "issues": [],
            "it_issues": [],
            "issue_results": [],
            "too_many_issues": False,
            "final_response": "",
            "citations": [],
            "images": [],
            "feedback_enabled": False,
            "ticket_intent": TicketIntent.NONE,
            "prior_pending_issues": [],
            "force_ticket_offer": False,
        }

    async def run(
        self, request: AgentRequest, *, correlation_id: str | None = None
    ) -> AgentState:
        result: AgentState = await self.graph.ainvoke(
            self._initial_state(request, correlation_id)
        )
        return result

    @staticmethod
    def _to_response(state: AgentState) -> AgentResponse:
        return AgentResponse(
            answer=state.get("final_response", ""),
            traceId=state["correlation_id"],
            correlationId=state["correlation_id"],
            citations=state.get("citations", []),
            images=state.get("images", []),
            issueResults=state.get("issue_results", []),
            feedbackEnabled=state.get("feedback_enabled", False),
        )

    async def respond(
        self, request: AgentRequest, *, correlation_id: str | None = None
    ) -> AgentResponse:
        return self._to_response(await self.run(request, correlation_id=correlation_id))

    async def stream(
        self, request: AgentRequest, *, correlation_id: str | None = None
    ) -> AsyncIterator[tuple[str, Any]]:
        """Run the graph, yielding progress stages before the final state.

        Yields ``("stage", label)`` as each node completes and finally
        ``("state", AgentState)`` -- the same state :meth:`run` returns, so
        callers build the ``AgentResponse`` and emit the spec §15.2 log line
        exactly as they do on the non-streaming path. The answer is identical
        to what :meth:`respond` produces for the same request: this streams
        *when* the user learns things, never *what* they learn.

        Why stages and not tokens: spec §5.3 requires the Response Builder to
        be deterministic string templating over answers that upstream nodes
        already finished producing, so at the point ``final_response`` exists
        there is no token stream left to forward. The latency a user actually
        waits through is issue extraction plus retrieval, which is exactly
        what these stages cover.

        ``stream_mode="updates"`` yields ``{node_name: delta}`` once per
        completed node. ``AgentState`` is a plain ``TypedDict`` with no
        reducer annotations, so LangGraph's own merge semantics are
        last-value-wins per key and folding the deltas here reproduces the
        same final state ``ainvoke`` would have returned.
        """
        state: AgentState = self._initial_state(request, correlation_id)

        async for update in self.graph.astream(dict(state), stream_mode="updates"):
            if not isinstance(update, dict):
                continue
            for node_name, delta in update.items():
                if isinstance(delta, dict):
                    state.update(delta)  # type: ignore[typeddict-item]
                label = STAGE_LABELS.get(node_name)
                if label:
                    yield "stage", label

        yield "state", state


@dataclass(frozen=True)
class WorkflowServices:
    """Bundle of collaborators an :class:`AgentWorkflow` needs.

    Purely a constructor-argument convenience for ``api.py``'s lifespan
    wiring; not used internally by the workflow itself.
    """

    extractor: IssueExtractor
    faq_service: FaqService
    knowledge_service: KnowledgeService
    conversation_service: ConversationService
    ticket_service: TicketService
