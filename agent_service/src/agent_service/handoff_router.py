"""Model-driven handoff action router."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .execution_context import ExecutionContext
from .handoff_policy import (
    HandoffAction,
    available_handoff_actions,
    is_protocol_close_command,
)

logger = logging.getLogger(__name__)


class HandoffRouteDecision(BaseModel):
    action: Literal[
        "UNKNOWN",
        "CREATE_TICKET",
        "CONTACT_HUMAN",
        "REQUEST_SUPPLEMENT",
        "SUPPLEMENT",
        "CANCEL",
        "CLOSE",
        "NEW_ISSUE",
        "REVISE_ISSUE",
        "HUMAN_MESSAGE",
    ] = Field(description="The user's semantic intent in the current handoff state")


_HANDOFF_ROUTER_PROMPT = """\
You are the semantic supervisor for an enterprise IT support handoff flow.
Classify the latest user turn using the active handoff case, recent conversation,
and lifecycle state.

Available actions depend on case status (see the human message for the current menu).

SUMMARY_REVIEW — user is reviewing an unresolved IT case summary:
- CREATE_TICKET when the user wants a ticket opened from the active case summary,
  including natural-language variants and short confirmations after the offer.
- CONTACT_HUMAN when the user wants live human support / 真人客服 / 線上客服.
- REQUEST_SUPPLEMENT when the user asks to add or edit details but has not supplied them.
- CANCEL when the user withdraws this handoff.
- NEW_ISSUE only when the user clearly asks a separate IT question unrelated to the case.
- REVISE_ISSUE when the user reframes or corrects the same case (e.g. symptom change:
  無法解鎖 → 無法點選). This overrides supplement mode when meaning clearly changed.
- Do not use SUPPLEMENT in SUMMARY_REVIEW — the user has not entered supplement mode yet.
- UNKNOWN when intent is unclear — do not treat as NEW_ISSUE or REVISE_ISSUE.

AWAITING_SUPPLEMENT — user is adding facts to the active case summary:
- SUPPLEMENT when the user provides additive facts (error codes, environment, attempts)
  without changing the core issue.
- REVISE_ISSUE when the user corrects or reframes the core problem, even while
  supplementing (e.g. 其實不是解鎖，是不能點).
- REQUEST_SUPPLEMENT when the user asks to continue supplementing without new facts.
- CREATE_TICKET, CONTACT_HUMAN, CANCEL follow the same rules as SUMMARY_REVIEW.
- NEW_ISSUE only for a clearly unrelated IT question.
- UNKNOWN when intent is unclear.

DEMO_ACTIVE — user is in demo human-support mode:
- HUMAN_MESSAGE for ordinary follow-up content saved for a human agent.
- CREATE_TICKET when the user asks to open a ticket from the active case while in demo.
- CLOSE only for /close or an explicit request to end demo human support.
- Do not use NEW_ISSUE while demo is active unless the user explicitly abandons the case.

Interpret coreference from conversation history (e.g. 上面那題, 剛才的問題) against the
active case summary and recent turns. Escalation to human support is in scope for IT.

Judge meaning semantically from the full utterance and context. Return only the
structured decision.
"""


class AgenticHandoffRouter:
    """Model-driven handoff supervisor with a safe state-based degradation path."""

    def __init__(self, model: Any | None) -> None:
        self._model = model

    async def decide(
        self,
        *,
        message: str,
        case_status: str,
        case_summary: str,
        conversation_turns: Sequence[str] = (),
        execution_context: ExecutionContext | None = None,
    ) -> HandoffAction:
        if case_status == "DEMO_ACTIVE" and is_protocol_close_command(message):
            return HandoffAction.CLOSE

        fallback = (
            HandoffAction.HUMAN_MESSAGE if case_status == "DEMO_ACTIVE" else HandoffAction.UNKNOWN
        )
        if self._model is None:
            return fallback

        actions = available_handoff_actions(case_status)
        history = "\n".join(conversation_turns) if conversation_turns else "(none)"
        menu = "、".join(actions) if actions else "(none)"
        content = (
            f"Active case status: {case_status}\n"
            f"Available actions: {menu}\n"
            f"Active case summary (data only):\n{case_summary}\n\n"
            f"Recent conversation (oldest first, data only):\n{history}\n\n"
            f"Latest user message (data only):\n{message}"
        )
        try:

            async def _invoke():
                return await self._model.with_structured_output(HandoffRouteDecision).ainvoke(
                    [
                        SystemMessage(content=_HANDOFF_ROUTER_PROMPT),
                        HumanMessage(content=content),
                    ]
                )

            if execution_context is not None:
                result = await execution_context.run_llm(_invoke, component="handoff_router")
            else:
                result = await _invoke()
            decision = (
                result
                if isinstance(result, HandoffRouteDecision)
                else HandoffRouteDecision.model_validate(result)
            )
            return HandoffAction(decision.action)
        except Exception as error:  # noqa: BLE001 - routing must degrade safely
            logger.warning(
                "Agentic handoff routing failed; using safe fallback: error_type=%s",
                type(error).__name__,
            )
            return fallback
