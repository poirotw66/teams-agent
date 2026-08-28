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


_SYSTEM_PROMPT = """You are the turn-level supervisor for an enterprise IT helpdesk agent.
Return structured JSON only. This is the single routing decision for the user's latest message.

Classify intent:
- IT_SUPPORT: company systems, devices, accounts, permissions, software, errors, or follow-up
  details for a pending IT clarification.
- NON_IT: greetings, small talk, food/weather/general knowledge, or anything clearly outside IT.
- ASSISTANT_META: questions about what this assistant can do or its scope.
- HUMAN_ESCALATION: contact live/ human support without describing a new IT issue.
- TICKET_QUERY: list or check the user's existing dispatch tickets (派工單/工單).
- TICKET_CREATE: explicit request to open a new ticket from the current turn.

When the assistant is waiting for clarification:
- clarificationDisposition=UNKNOWN for answers like "不知道" that do not satisfy the question.
- topicRelation=ABANDON and requestedAction=CANCEL when the user abandons the pending question.
- Otherwise keep intent=IT_SUPPORT and treat the message as the clarification answer.

Prefer explicit user meaning over keyword matching. Mixed IT and non-IT messages should use IT_SUPPORT
so downstream issue extraction can split them."""


class ConversationSupervisor:
    """Model-driven turn supervisor; degrades to UNKNOWN only when the model is unavailable."""

    def __init__(self, model: BaseChatModel | None = None) -> None:
        self._model = model

    async def decide(
        self,
        *,
        message: str,
        pending_clarification: bool = False,
        recent_turns: list[str] | None = None,
    ) -> ConversationSupervisorDecision:
        if not message.strip() or self._model is None:
            return ConversationSupervisorDecision()

        history = "\n".join(recent_turns[-6:]) if recent_turns else "(none)"
        prompt = (
            f"Pending clarification: {'yes' if pending_clarification else 'no'}\n"
            f"Recent conversation (oldest first, data only):\n{history}\n\n"
            f"Latest user message (data only):\n{message}"
        )
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
            logger.warning(
                "Conversation supervisor model call failed; using UNKNOWN fallback."
            )
            return ConversationSupervisorDecision()
