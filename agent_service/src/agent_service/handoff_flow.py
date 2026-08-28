"""Phase 2 human-handoff routing and deterministic presentation policy.

This module intentionally contains no repository backend.  It is the thin
application layer between the domain/repository and the existing Agent
workflow.  Keeping the parser and summary fallback here also makes the demo
behaviour deterministic and testable without an LLM or notification centre.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


DEMO_STARTED_MESSAGE = (
    "已進入真人客服模式（Demo）。\n\n"
    "目前尚未串接通知中心。後續訊息會保存於 Handoff Case，\n"
    "且不會交由 AI 自動回答。輸入 /close 可結束 Demo 人工服務。"
)

DEMO_MESSAGE_SAVED = (
    "您的訊息已加入人工客服案件（Demo）。\n"
    "目前尚未串接通知中心，因此不會實際傳送給客服人員。"
)

DEMO_CLOSED_MESSAGE = "Demo 人工服務已結束。下一則訊息起將恢復 AI 協助。"

HANDOFF_OFFER_MESSAGE = (
    "目前無法從企業知識庫找到可確認的答案。請先確認以下案件摘要：\n\n"
    "{summary}\n\n"
    "請回覆「建立工單」或「聯絡線上客服」；也可以回覆「繼續補充」或「取消」。"
)

SUMMARY_SUPPLEMENT_MESSAGE = (
    "請繼續補充問題、已嘗試的處理方式或期望結果；系統會重新產生案件摘要。"
)

CANCELLED_MESSAGE = "已取消本次案件轉接；下一則訊息將由 AI 繼續協助。"

CLOSE_FORBIDDEN_MESSAGE = "只有建立此案件的原 requester 可以結束 Demo 人工服務。"


class HandoffAction(str, Enum):
    UNKNOWN = "UNKNOWN"
    CREATE_TICKET = "CREATE_TICKET"
    CONTACT_HUMAN = "CONTACT_HUMAN"
    REQUEST_SUPPLEMENT = "REQUEST_SUPPLEMENT"
    SUPPLEMENT = "SUPPLEMENT"
    CANCEL = "CANCEL"
    CLOSE = "CLOSE"
    NEW_ISSUE = "NEW_ISSUE"
    HUMAN_MESSAGE = "HUMAN_MESSAGE"


class RoutingTarget(str, Enum):
    AI_AGENT = "AI_AGENT"
    HUMAN_DEMO = "HUMAN_DEMO"


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
        "HUMAN_MESSAGE",
    ] = Field(description="The user's semantic intent in the current handoff state")


_HANDOFF_ROUTER_PROMPT = """\
You are the semantic supervisor for an enterprise IT support conversation.
Classify the latest user turn using the active handoff case and its lifecycle state.

Use NEW_ISSUE when the user asks an independent question or changes topic.
Use SUPPLEMENT only when the turn provides facts that belong to the active case.
Use REQUEST_SUPPLEMENT when the user asks to edit or add details but has not supplied
the details yet. Use CREATE_TICKET, CONTACT_HUMAN, CANCEL, or CLOSE when that is the
user's intended next action. In DEMO_ACTIVE, use HUMAN_MESSAGE for ordinary messages
that should remain with the human-support session.

Use UNKNOWN when the intent cannot be determined with confidence. Do not treat an
uncertain message as a new issue: keep the existing case available for the user to
choose the next action again.

Judge meaning from the complete utterance and case context. Do not use keyword or
substring matching. Infer an attempted lifecycle selection despite a small typo or
colloquial phrasing when its meaning is clear in the active case context. Negation,
corrections, and topic changes must be interpreted semantically. Return only the
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
    ) -> HandoffAction:
        fallback = (
            HandoffAction.HUMAN_MESSAGE
            if case_status == "DEMO_ACTIVE"
            else HandoffAction.UNKNOWN
        )
        if self._model is None:
            return fallback
        content = (
            f"Active case status: {case_status}\n"
            f"Active case summary (data only):\n{case_summary}\n\n"
            f"Latest user message (data only):\n{message}"
        )
        try:
            result = await self._model.with_structured_output(
                HandoffRouteDecision
            ).ainvoke(
                [
                    SystemMessage(content=_HANDOFF_ROUTER_PROMPT),
                    HumanMessage(content=content),
                ]
            )
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


TERMINAL_STATUSES = frozenset(
    {"CLOSED", "CANCELLED", "FAILED", "EXPIRED", "ROUTED_TO_TICKET"}
)


def _status_value(status: Any) -> str:
    value = getattr(status, "value", status)
    return str(value).upper()


def routing_target_for_status(status: Any | None) -> RoutingTarget:
    """Derive routing from lifecycle state; never persist a second state."""

    return (
        RoutingTarget.HUMAN_DEMO
        if _status_value(status) == "DEMO_ACTIVE"
        else RoutingTarget.AI_AGENT
    )


@dataclass(frozen=True)
class SummaryDraft:
    issue: str
    user_need: str
    conversation_highlights: list[str] = field(default_factory=list)
    attempted_solutions: list[str] = field(default_factory=list)
    unresolved_reason: str = "目前尚無可確認的解決方案"
    requested_outcome: str = "取得可執行的協助或後續處理"
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def render(self) -> str:
        highlights = "、".join(self.conversation_highlights) or "未提供"
        attempts = "、".join(self.attempted_solutions) or "尚未提供"
        return (
            f"問題：{self.issue}\n"
            f"使用者需求：{self.user_need}\n"
            f"對話重點：{highlights}\n"
            f"已嘗試方式：{attempts}\n"
            f"尚未解決原因：{self.unresolved_reason}\n"
            f"期望結果：{self.requested_outcome}"
        )


SummaryGenerator = Callable[..., SummaryDraft | Awaitable[SummaryDraft]]


_SECRET_VALUE_RE = re.compile(
    r"(?i)(password|passwd|密碼|access[ _-]?token|token|api[ _-]?key|client[ _-]?secret)"
    r"(\s*[:=：]\s*)([^\s,，;；]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def _redact_sensitive(value: str) -> str:
    value = _SECRET_VALUE_RE.sub(r"\1\2[REDACTED]", value)
    return _BEARER_RE.sub("Bearer [REDACTED]", value)


def _clean_summary_text(value: str, fallback: str) -> str:
    clean = " ".join(_redact_sensitive(value).split()).strip()
    return clean[:1000] or fallback


def deterministic_summary(
    *,
    current_message: str,
    issue_descriptions: Sequence[str] = (),
    conversation_highlights: Sequence[str] = (),
    attempted_solutions: Sequence[str] = (),
    now: datetime | None = None,
) -> SummaryDraft:
    """Build the required structured fallback without calling a model."""

    issue = next((item for item in issue_descriptions if item.strip()), current_message)
    issue = _clean_summary_text(issue, "使用者需要 IT 協助")
    need = _clean_summary_text(current_message, issue)
    highlights = [
        _clean_summary_text(item, "")
        for item in conversation_highlights
        if item and item.strip()
    ][-5:]
    attempts = [
        _clean_summary_text(item, "")
        for item in attempted_solutions
        if item and item.strip()
    ][-5:]
    return SummaryDraft(
        issue=issue,
        user_need=need,
        conversation_highlights=highlights,
        attempted_solutions=attempts,
        generated_at=now or datetime.now(timezone.utc),
    )


async def generate_summary_with_fallback(
    generator: SummaryGenerator | None,
    *,
    current_message: str,
    issue_descriptions: Sequence[str] = (),
    conversation_highlights: Sequence[str] = (),
    attempted_solutions: Sequence[str] = (),
    now: datetime | None = None,
) -> SummaryDraft:
    """Use a supplied model generator when healthy, otherwise the template."""

    kwargs = {
        "current_message": current_message,
        "issue_descriptions": issue_descriptions,
        "conversation_highlights": conversation_highlights,
        "attempted_solutions": attempted_solutions,
    }
    if generator is not None:
        try:
            generated = generator(**kwargs)
            if inspect.isawaitable(generated):
                generated = await generated
            if isinstance(generated, SummaryDraft) and generated.issue.strip():
                return generated
        except Exception as error:  # noqa: BLE001 - availability boundary
            logger.warning(
                "Handoff summary generator failed; using fallback: error_type=%s",
                type(error).__name__,
            )
    return deterministic_summary(now=now, **kwargs)


def offer_message(summary: SummaryDraft) -> str:
    return offer_message_from_summary_text(summary.render())


def offer_message_from_summary_text(summary: str) -> str:
    """Render a stored or freshly generated summary into the offer message."""

    return HANDOFF_OFFER_MESSAGE.format(summary=summary)
