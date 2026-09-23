"""Handoff action policy, messages, and authorization gates."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from .confirmation import TicketIntent, classify_ticket_intent
from .extractor import _is_human_escalation_request

DEMO_STARTED_MESSAGE = (
    "已進入真人客服模式（Demo）。\n\n"
    "目前尚未串接通知中心。後續訊息會保存於 Handoff Case，\n"
    "且不會交由 AI 自動回答。輸入 /close 可結束 Demo 人工服務。"
)

DEMO_MESSAGE_SAVED = (
    "您的訊息已加入人工客服案件（Demo）。\n目前尚未串接通知中心，因此不會實際傳送給客服人員。"
)

DEMO_CLOSED_MESSAGE = "Demo 人工服務已結束。下一則訊息起將恢復 AI 協助。"

HANDOFF_OFFER_MESSAGE = (
    "目前無法從企業知識庫找到可確認的答案。\n\n"
    "**請確認你的問題**\n\n{summary}\n\n"
    "接下來可以回覆：\n\n"
    "- **建立派工單** 或 **聯絡線上客服**\n"
    "- **繼續補充**（例如錯誤訊息或已嘗試方式）或 **取消**"
)

SUMMARY_SUPPLEMENT_MESSAGE = "請繼續補充問題、已嘗試的處理方式或期望結果；系統會重新產生案件摘要。"

CANCELLED_MESSAGE = "已取消本次案件轉接；下一則訊息將由 AI 繼續協助。"

CLOSE_FORBIDDEN_MESSAGE = "只有建立此案件的原 requester 可以結束 Demo 人工服務。"

_SUMMARY_REVIEW_ACTIONS = (
    "建立派工單",
    "聯絡線上客服",
    "繼續補充",
    "取消",
)
_DEMO_ACTIVE_ACTIONS = (
    "一般訊息（保存至人工案件）",
    "建立派工單（依案件摘要）",
    "/close（結束 Demo 人工服務）",
)


class HandoffAction(str, Enum):
    UNKNOWN = "UNKNOWN"
    CREATE_TICKET = "CREATE_TICKET"
    CONTACT_HUMAN = "CONTACT_HUMAN"
    REQUEST_SUPPLEMENT = "REQUEST_SUPPLEMENT"
    SUPPLEMENT = "SUPPLEMENT"
    CANCEL = "CANCEL"
    CLOSE = "CLOSE"
    NEW_ISSUE = "NEW_ISSUE"
    REVISE_ISSUE = "REVISE_ISSUE"
    HUMAN_MESSAGE = "HUMAN_MESSAGE"


HandoffResumeReason = Literal["NONE", "NEW_ISSUE", "REVISED_ISSUE"]


class RoutingTarget(str, Enum):
    AI_AGENT = "AI_AGENT"
    HUMAN_DEMO = "HUMAN_DEMO"


TERMINAL_STATUSES = frozenset({"CLOSED", "CANCELLED", "FAILED", "EXPIRED", "ROUTED_TO_TICKET"})

# Fail-closed legal state × action transitions. Router outputs outside this
# table become UNKNOWN and must not mutate the case (re-offer / stay put).
_LEGAL_HANDOFF_ACTIONS: dict[str, frozenset[HandoffAction]] = {
    "SUMMARY_REVIEW": frozenset(
        {
            HandoffAction.CREATE_TICKET,
            HandoffAction.CONTACT_HUMAN,
            HandoffAction.REQUEST_SUPPLEMENT,
            HandoffAction.CANCEL,
            HandoffAction.CLOSE,
            HandoffAction.NEW_ISSUE,
            HandoffAction.REVISE_ISSUE,
        }
    ),
    "AWAITING_SUPPLEMENT": frozenset(
        {
            HandoffAction.SUPPLEMENT,
            HandoffAction.REQUEST_SUPPLEMENT,
            HandoffAction.CREATE_TICKET,
            HandoffAction.CONTACT_HUMAN,
            HandoffAction.CANCEL,
            HandoffAction.CLOSE,
            HandoffAction.NEW_ISSUE,
            HandoffAction.REVISE_ISSUE,
        }
    ),
    "DEMO_ACTIVE": frozenset(
        {
            HandoffAction.HUMAN_MESSAGE,
            HandoffAction.CREATE_TICKET,
            HandoffAction.CLOSE,
        }
    ),
}


def available_handoff_actions(case_status: str) -> tuple[str, ...]:
    if case_status == "DEMO_ACTIVE":
        return _DEMO_ACTIVE_ACTIONS
    if case_status in {"SUMMARY_REVIEW", "AWAITING_SUPPLEMENT"}:
        return _SUMMARY_REVIEW_ACTIONS
    return ()


def is_legal_handoff_transition(case_status: str, action: HandoffAction) -> bool:
    """Return True when ``action`` is allowed for ``case_status`` (fail-closed)."""
    if action is HandoffAction.UNKNOWN:
        return True
    allowed = _LEGAL_HANDOFF_ACTIONS.get(case_status)
    if allowed is None:
        return False
    return action in allowed


def validate_handoff_action(case_status: str, action: HandoffAction) -> HandoffAction:
    """Reject illegal model outputs; semantics come from the model, legality from workflow."""
    if not is_legal_handoff_transition(case_status, action):
        return HandoffAction.UNKNOWN
    return action


def is_protocol_close_command(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {"/close", "close"}


def authorize_handoff_action(
    case_status: str,
    action: HandoffAction,
    *,
    message: str,
) -> HandoffAction:
    """Require deterministic evidence before privileged handoff actions."""
    validated = validate_handoff_action(case_status, action)
    if validated is HandoffAction.CREATE_TICKET:
        if classify_ticket_intent(message) is not TicketIntent.CREATE:
            return HandoffAction.UNKNOWN
    if validated is HandoffAction.CONTACT_HUMAN:
        if not _is_human_escalation_request(message):
            return HandoffAction.UNKNOWN
    if validated is HandoffAction.CLOSE and not is_protocol_close_command(message):
        return HandoffAction.UNKNOWN
    return validated


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    return str(value).upper()


def routing_target_for_status(status: object | None) -> RoutingTarget:
    """Derive routing from lifecycle state; never persist a second state."""

    return (
        RoutingTarget.HUMAN_DEMO
        if _status_value(status) == "DEMO_ACTIVE"
        else RoutingTarget.AI_AGENT
    )
