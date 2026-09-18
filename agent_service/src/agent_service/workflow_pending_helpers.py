"""Pending-ticket and follow-up helpers for the agent workflow."""

from __future__ import annotations

from .contracts import ConversationContext, Issue, PendingIssueContext
from .extractor import (
    _GENERIC_TICKET_DESCRIPTION,
    _is_generic_ticket_description,
    _is_generic_ticket_request,
    _strip_ticket_command,
    merge_pending_ticket_issues,
)
from .sanitize import sanitize_description

_TICKET_OFFER_MARKER = "是否需要協助建立派工單"
_TICKET_DETAIL_QUESTION = "請描述需要建立派工單的 IT 問題，例如使用的系統、功能或錯誤訊息。"


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
    if last.role == "assistant" and last.followUpState == "AWAITING_CLARIFICATION":
        return list(last.pendingIssues)
    return []


def _conversation_turns_for_supervisor(conversation: ConversationContext) -> list[str]:
    turns: list[str] = []
    for message in conversation.messages[-6:]:
        role = "User" if message.role == "user" else "Assistant"
        turns.append(f"{role}: {message.text[:200]}")
    return turns


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


def _pending_context_to_ready_issue(pending: PendingIssueContext, *, issue_id: int) -> Issue:
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
        context for context in contexts if not _is_generic_ticket_description(context.description)
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


def _is_pending_ticket_detail(
    pending_issues: list[PendingIssueContext],
) -> bool:
    return bool(pending_issues) and all(pending.route == "TICKET" for pending in pending_issues)


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
