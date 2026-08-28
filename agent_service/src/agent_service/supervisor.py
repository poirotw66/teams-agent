"""Structured conversation supervisor decisions for active workflow paths."""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SupervisorIntent = Literal[
    "IT_SUPPORT",
    "TICKET_QUERY",
    "TICKET_CREATE",
    "HUMAN_ESCALATION",
    "ASSISTANT_META",
    "NON_IT",
    "UNKNOWN",
]
TopicRelation = Literal["SAME", "NEW", "META", "ABANDON"]
RequestedAction = Literal[
    "NONE",
    "ANSWER",
    "CLARIFY",
    "CREATE_TICKET",
    "CONTACT_HUMAN",
    "QUERY_TICKETS",
    "CANCEL",
    "CLOSE",
]
ClarificationDisposition = Literal["ANSWER", "UNKNOWN", "ABANDON", "NONE"]


class ConversationSupervisorDecision(BaseModel):
    intent: SupervisorIntent = "UNKNOWN"
    topicRelation: TopicRelation = "SAME"
    requestedAction: RequestedAction = "NONE"
    clarificationDisposition: ClarificationDisposition = "NONE"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


_SYSTEM_PROMPT = """You classify the user's latest message in an enterprise IT helpdesk chat.
Return structured JSON only. Prefer explicit user intent over keyword guessing.
Use clarificationDisposition=UNKNOWN for short answers like "不知道" that cannot satisfy a pending question.
Use topicRelation=ABANDON when the user cancels or switches away from a pending clarification.
Use intent=ASSISTANT_META for questions about what the assistant can do.
Use intent=HUMAN_ESCALATION when the user asks to contact live support without describing a new IT issue.
Use intent=TICKET_QUERY when the user asks to list or check their tickets."""


class ConversationSupervisor:
    """Model-driven supervisor with deterministic fallbacks for trust boundaries."""

    def __init__(self, model: BaseChatModel | None = None) -> None:
        self._model = model

    @staticmethod
    def deterministic(message: str, *, pending_clarification: bool = False) -> ConversationSupervisorDecision:
        normalized = message.strip().lower().rstrip("。.!！?？")
        if not normalized:
            return ConversationSupervisorDecision()

        if pending_clarification:
            if _is_abandon(normalized):
                return ConversationSupervisorDecision(
                    intent="IT_SUPPORT",
                    topicRelation="ABANDON",
                    requestedAction="CANCEL",
                    clarificationDisposition="ABANDON",
                    confidence=1.0,
                )
            if _is_unknown_answer(normalized):
                return ConversationSupervisorDecision(
                    intent="IT_SUPPORT",
                    topicRelation="SAME",
                    requestedAction="NONE",
                    clarificationDisposition="UNKNOWN",
                    confidence=1.0,
                )

        if _is_assistant_scope(normalized):
            return ConversationSupervisorDecision(
                intent="ASSISTANT_META",
                topicRelation="META",
                requestedAction="ANSWER",
                confidence=1.0,
            )
        if _is_human_escalation(normalized):
            return ConversationSupervisorDecision(
                intent="HUMAN_ESCALATION",
                topicRelation="SAME",
                requestedAction="CONTACT_HUMAN",
                confidence=0.95,
            )
        if _is_ticket_query(normalized):
            return ConversationSupervisorDecision(
                intent="TICKET_QUERY",
                topicRelation="SAME",
                requestedAction="QUERY_TICKETS",
                confidence=0.95,
            )
        return ConversationSupervisorDecision()

    async def decide(
        self,
        *,
        message: str,
        pending_clarification: bool = False,
        recent_turns: list[str] | None = None,
    ) -> ConversationSupervisorDecision:
        fallback = self.deterministic(message, pending_clarification=pending_clarification)
        if fallback.intent != "UNKNOWN" or self._model is None:
            return fallback
        prompt = message
        if recent_turns:
            prompt = "Recent conversation:\n" + "\n".join(recent_turns[-6:]) + f"\n\nLatest user message:\n{message}"
        try:
            result = await self._model.with_structured_output(
                ConversationSupervisorDecision
            ).ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            if isinstance(result, ConversationSupervisorDecision):
                return result
            return ConversationSupervisorDecision.model_validate(result)
        except Exception:  # noqa: BLE001 - supervisor must degrade safely
            logger.warning("Conversation supervisor model call failed; using deterministic fallback.")
            return fallback


def _is_unknown_answer(normalized: str) -> bool:
    if len(normalized) > 24:
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


def _is_abandon(normalized: str) -> bool:
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


def _is_assistant_scope(normalized: str) -> bool:
    markers = (
        "你能回答什麼",
        "你可以回答什麼",
        "你能做什麼",
        "你可以做什麼",
        "你會什麼",
        "你的功能",
        "你的範圍",
    )
    return any(marker in normalized for marker in markers)


def _is_human_escalation(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    markers = (
        "聯絡線上客服",
        "联系线上客服",
        "聯繫線上客服",
        "联系線上客服",
        "找線上客服",
        "找线上客服",
        "真人客服",
        "人工客服",
        "轉真人",
        "转真人",
    )
    return any(marker in compact for marker in markers)


def _is_ticket_query(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    markers = (
        "我的工單",
        "我的派工單",
        "我有哪些工單",
        "我有哪些派工單",
        "查詢工單",
        "查詢派工單",
        "查我的工單",
        "查我的派工單",
    )
    if any(marker in compact for marker in markers):
        return True
    return compact.startswith("我的") and len(compact) <= 12
