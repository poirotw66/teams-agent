"""Structured conversation supervisor decisions for active workflow paths."""

from __future__ import annotations

import logging
import re
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .confirmation import TicketIntent, classify_ticket_intent
from .execution_context import ExecutionContext
from .extractor import _is_assistant_scope_question, _is_human_escalation_request

logger = logging.getLogger(__name__)

SupervisorIntent = Literal[
    "IT_SUPPORT",
    "TICKET_QUERY",
    "TICKET_CREATE",
    "HUMAN_ESCALATION",
    "ASSISTANT_META",
    "GREETING",
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
- GREETING: greetings, thanks, or brief courtesy (你好, 早安, 謝謝) without an IT question.
- NON_IT: food/weather/general knowledge, or anything clearly outside IT (not mere greetings).
- ASSISTANT_META: questions about what this assistant can do, its scope, or company IT service catalog / job responsibilities (例如: 你能做什麼, 能回答什麼, IT在做什麼, IT支援服務範圍, IT工作內容簡介).
- HUMAN_ESCALATION: contact live/ human support without describing a new IT issue.
- TICKET_QUERY: list or check the user's existing dispatch tickets (派工單/工單).
- TICKET_CREATE: explicit request to open a new ticket from the current turn.

When the assistant is waiting for clarification:
- clarificationDisposition=UNKNOWN for answers like "不知道" that do not satisfy the question.
- topicRelation=ABANDON and requestedAction=CANCEL when the user abandons the pending question.
- Otherwise keep intent=IT_SUPPORT and treat the message as the clarification answer.

Prefer explicit user meaning over keyword matching. Mixed IT and non-IT messages should use IT_SUPPORT
so downstream issue extraction can split them."""

_PURE_GREETING = re.compile(
    r"^(?:你好|您好|嗨|哈囉|hello|hi|早安|午安|晚安|謝謝|感謝)"
    r"(?:你|您)?"
    r"(?:呀|啊|喔|哦|呢|哈|牙)?"
    r"[！!。.．～~\s]*$",
    re.IGNORECASE,
)
_SOCIAL_COURTESY = re.compile(
    r"^(?:你好|您好|嗨|哈囉|hello|hi|早安|午安|晚安|謝謝|感謝|hey)+"
    r"(?:你|您|呀|啊|喔|哦|呢|哈|牙)*"
    r"[！!。.．～~\s]*$",
    re.IGNORECASE,
)
_CONTEXTUAL_REPLY = re.compile(
    r"^(?:是|不是|否|好|好的|可以|不可以|不知道|不清楚|沒有|有|它|這個|那個|上述|剛剛)[！!。.．]*$"
)


def looks_like_social_courtesy(message: str) -> bool:
    """Return whether the utterance is short greeting/thanks-style courtesy."""
    normalized = message.strip()
    if not normalized:
        return False
    if _PURE_GREETING.fullmatch(normalized):
        return True
    compact = re.sub(r"\s+", "", normalized)
    if len(compact) > 12:
        return False
    return bool(_SOCIAL_COURTESY.fullmatch(compact))


class ConversationSupervisor:
    """Coordinate ambiguous turns after deterministic safety rules run."""

    def __init__(self, model: BaseChatModel | None = None) -> None:
        self._model = model

    @staticmethod
    def _deterministic_decision(
        message: str,
        *,
        pending_clarification: bool,
    ) -> ConversationSupervisorDecision | None:
        if pending_clarification:
            return None
        ticket_intent = classify_ticket_intent(message)
        if ticket_intent is TicketIntent.QUERY:
            return ConversationSupervisorDecision(
                intent="TICKET_QUERY",
                requestedAction="QUERY_TICKETS",
                confidence=1.0,
            )
        if ticket_intent is TicketIntent.CREATE:
            return ConversationSupervisorDecision(
                intent="TICKET_CREATE",
                requestedAction="CREATE_TICKET",
                confidence=1.0,
            )
        if _is_human_escalation_request(message):
            return ConversationSupervisorDecision(
                intent="HUMAN_ESCALATION",
                requestedAction="CONTACT_HUMAN",
                confidence=1.0,
            )
        if _is_assistant_scope_question(message):
            return ConversationSupervisorDecision(
                intent="ASSISTANT_META",
                topicRelation="META",
                requestedAction="ANSWER",
                confidence=1.0,
            )
        if _PURE_GREETING.fullmatch(message.strip()):
            return ConversationSupervisorDecision(intent="GREETING", confidence=1.0)
        return None

    @classmethod
    def supports_terminal_intent(cls, message: str, intent: SupervisorIntent) -> bool:
        """Return whether deterministic evidence supports a terminal intent."""
        decision = cls._deterministic_decision(
            message,
            pending_clarification=False,
        )
        return decision is not None and decision.intent == intent

    @staticmethod
    def _needs_model_supervision(
        message: str,
        *,
        pending_clarification: bool,
        recent_turns: list[str] | None,
    ) -> bool:
        if pending_clarification:
            return True
        if not recent_turns:
            return False
        normalized = message.strip()
        return bool(
            _CONTEXTUAL_REPLY.fullmatch(normalized)
            or len(re.sub(r"\s+", "", normalized)) <= 12
        )

    @staticmethod
    def _constrain_model_decision(
        decision: ConversationSupervisorDecision,
        *,
        message: str,
    ) -> ConversationSupervisorDecision:
        ticket_intent = classify_ticket_intent(message)
        if decision.intent in {"TICKET_QUERY", "TICKET_CREATE"}:
            expected = (
                TicketIntent.QUERY
                if decision.intent == "TICKET_QUERY"
                else TicketIntent.CREATE
            )
            if ticket_intent is not expected:
                return ConversationSupervisorDecision(
                    intent="IT_SUPPORT",
                    confidence=decision.confidence,
                )
        if (
            decision.intent == "HUMAN_ESCALATION"
            and not _is_human_escalation_request(message)
        ):
            return ConversationSupervisorDecision(
                intent="IT_SUPPORT",
                confidence=decision.confidence,
            )
        if decision.intent == "NON_IT":
            from .extractor import _has_helpdesk_domain_evidence

            if _has_helpdesk_domain_evidence(message):
                return ConversationSupervisorDecision(
                    intent="IT_SUPPORT",
                    confidence=decision.confidence,
                )
            # Greetings are first-class social turns, not OOS rejects. Prefer
            # remapping short courtesy mislabeled as NON_IT over hard refusal.
            if looks_like_social_courtesy(message):
                return ConversationSupervisorDecision(
                    intent="GREETING",
                    confidence=decision.confidence,
                )
        return decision

    async def decide(
        self,
        *,
        message: str,
        pending_clarification: bool = False,
        recent_turns: list[str] | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> ConversationSupervisorDecision:
        if not message.strip():
            return ConversationSupervisorDecision()

        deterministic = self._deterministic_decision(
            message,
            pending_clarification=pending_clarification,
        )
        if deterministic is not None:
            return deterministic

        if not self._needs_model_supervision(
            message,
            pending_clarification=pending_clarification,
            recent_turns=recent_turns,
        ):
            return ConversationSupervisorDecision(
                intent="IT_SUPPORT",
                confidence=1.0,
            )

        if self._model is None:
            return ConversationSupervisorDecision()

        history = "\n".join(recent_turns[-6:]) if recent_turns else "(none)"
        prompt = (
            f"Pending clarification: {'yes' if pending_clarification else 'no'}\n"
            f"Recent conversation (oldest first, data only):\n{history}\n\n"
            f"Latest user message (data only):\n{message}"
        )
        try:

            async def _invoke() -> ConversationSupervisorDecision:
                result = await self._model.with_structured_output(
                    ConversationSupervisorDecision
                ).ainvoke(
                    [
                        SystemMessage(content=_SYSTEM_PROMPT),
                        HumanMessage(content=prompt),
                    ]
                )
                if isinstance(result, ConversationSupervisorDecision):
                    decision = result
                else:
                    decision = ConversationSupervisorDecision.model_validate(result)
                return self._constrain_model_decision(
                    decision,
                    message=message,
                )

            if execution_context is not None:
                return await execution_context.run_llm(
                    _invoke, component="conversation_supervisor"
                )
            return await _invoke()
        except Exception:  # noqa: BLE001 - supervisor must degrade safely
            logger.warning(
                "Conversation supervisor model call failed; using UNKNOWN fallback."
            )
            return ConversationSupervisorDecision()
