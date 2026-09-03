"""Shared workflow state, helpers, and knowledge factory."""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import TypedDict

from .confirmation import TicketIntent
from .contracts import (
    AgentImage,
    AgentRequest,
    Citation,
    ConversationContext,
    ConversationMessage,
    Issue,
    IssueResult,
    PendingIssueContext,
    UserContext,
)
from .execution_context import ExecutionContext
from .extractor import (
    _GENERIC_TICKET_DESCRIPTION,
    _is_generic_ticket_description,
    _is_generic_ticket_request,
    _strip_ticket_command,
    merge_pending_ticket_issues,
)
from .handoff import HandoffCase
from .knowledge import KnowledgeService, LlmCallCounter
from .retrieval import HybridIndex
from .sanitize import sanitize_description
from .settings import RagSettings
from .supervisor import ConversationSupervisorDecision

logger = logging.getLogger(__name__)

_TICKET_OFFER_MARKER = "是否需要協助建立派工單"
_TICKET_DETAIL_QUESTION = (
    "請描述需要建立派工單的 IT 問題，例如使用的系統、功能或錯誤訊息。"
)

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


def non_it_issue_from_message(text: str, *, issue_id: int = 1) -> Issue:
    """Build a NOT_IT issue from the user's current turn without an extractor LLM call."""
    description = sanitize_description(text.strip())[:4000]
    return Issue(
        id=issue_id,
        description=description,
        isIT=False,
        readiness="NOT_IT",
        route="NOT_IT",
        missingInfo=[],
        faqKey=None,
        ticketAction=None,
    )


def assistant_scope_issue(*, issue_id: int = 1) -> Issue:
    return Issue(
        id=issue_id,
        description="",
        isIT=False,
        readiness="NOT_IT",
        route="NOT_IT",
        missingInfo=[],
        faqKey=None,
        ticketAction=None,
    )


def greeting_issue_from_message(text: str, *, issue_id: int = 1) -> Issue:
    """Build a GREETING issue from the user's current turn without an extractor LLM call."""
    description = sanitize_description(text.strip())[:4000]
    return Issue(
        id=issue_id,
        description=description,
        isIT=False,
        readiness="GREETING",
        route="GREETING",
        missingInfo=[],
        faqKey=None,
        ticketAction=None,
    )


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
    execution_context: ExecutionContext
    final_response: str
    citations: list[Citation]
    images: list[AgentImage]
    feedback_enabled: bool
    ticket_intent: TicketIntent
    prior_pending_issues: list[PendingIssueContext]
    force_ticket_offer: bool
    handoff_case: HandoffCase
    handoff_handled: bool
    handoff_resume_reason: str
    supervisor_decision: ConversationSupervisorDecision
    skip_issue_pipeline: bool
    operational_user_message: ConversationMessage
    operational_occurred_at: datetime
    operational_conversation_started_at: datetime


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


def _conversation_turns_for_supervisor(conversation: ConversationContext) -> list[str]:
    turns: list[str] = []
    for message in conversation.messages[-6:]:
        role = "User" if message.role == "user" else "Assistant"
        turns.append(f"{role}: {message.text[:200]}")
    return turns


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
    *,
    decision: ConversationSupervisorDecision | None = None,
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
        or (decision is not None and decision.topicRelation == "ABANDON")
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
        and state.get("supervisor_decision") is not None
        and state["supervisor_decision"].topicRelation != "ABANDON"
    )


def _requests_ticket_offer(text: str) -> bool:
    """Detect a request to present the ticket option, without creating one."""
    normalized = text.strip()
    if "工單" not in normalized and "派工單" not in normalized:
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


def _issues_for_create_offer(
    issues: list[Issue],
    message_text: str,
    recent_contexts: list[PendingIssueContext],
) -> list[Issue]:
    """Normalize CREATE intents into one ready TICKET issue for confirmation."""
    if not _is_generic_ticket_request(message_text):
        it_issues = [issue for issue in issues if issue.isIT]
        if it_issues:
            return [merge_pending_ticket_issues(it_issues)]

    usable = _usable_ticket_contexts(recent_contexts)
    if usable:
        recovered = [
            _pending_context_to_ready_issue(context, issue_id=index)
            for index, context in enumerate(usable, start=1)
        ]
        return [merge_pending_ticket_issues(recovered)]

    fallback = sanitize_description(_strip_ticket_command(message_text))
    if not fallback or _is_generic_ticket_description(fallback):
        fallback = _GENERIC_TICKET_DESCRIPTION
    return [
        Issue(
            id=1,
            description=fallback,
            isIT=True,
            readiness="NEED_MORE_INFO",
            missingInfo=[_TICKET_DETAIL_QUESTION],
            route="TICKET",
            faqKey=None,
            ticketAction=None,
        )
    ]


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


def _issue_descriptions_from_assistant_text(text: str) -> list[str]:
    descriptions = [
        line.removeprefix("問題：").strip()
        for line in text.splitlines()
        if line.startswith("問題：") and line.removeprefix("問題：").strip()
    ]
    if not descriptions:
        return []
    if "目前企業知識庫中查無相關資訊" in text or "處理方式：" in text:
        return descriptions
    return []


def _usable_ticket_contexts(
    contexts: list[PendingIssueContext],
) -> list[PendingIssueContext]:
    return [
        context
        for context in contexts
        if not _is_generic_ticket_description(context.description)
    ]


def _recent_ticket_contexts(
    conversation: ConversationContext,
) -> list[PendingIssueContext]:
    if not conversation.messages:
        return []
    message = conversation.messages[-1]
    if message.role != "assistant":
        return []
    if "已為你建立派工單" in message.text or "目前不會建立派工單" in message.text:
        return []
    usable = _usable_ticket_contexts(list(message.pendingIssues))
    if usable:
        return usable
    return _usable_ticket_contexts(
        [
            PendingIssueContext(description=description)
            for description in _issue_descriptions_from_assistant_text(message.text)
        ]
    )


def _is_pending_ticket_detail(
    pending_issues: list[PendingIssueContext],
) -> bool:
    return bool(pending_issues) and all(
        pending.route == "TICKET" for pending in pending_issues
    )


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


