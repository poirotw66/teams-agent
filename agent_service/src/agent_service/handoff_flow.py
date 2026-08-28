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
from typing import Any, Protocol

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
    CREATE_TICKET = "CREATE_TICKET"
    CONTACT_HUMAN = "CONTACT_HUMAN"
    SUPPLEMENT = "SUPPLEMENT"
    CANCEL = "CANCEL"
    CLOSE = "CLOSE"
    NONE = "NONE"


class RoutingTarget(str, Enum):
    AI_AGENT = "AI_AGENT"
    HUMAN_DEMO = "HUMAN_DEMO"


_SPACE_RE = re.compile(r"\s+")
_EDGE_PUNCTUATION_RE = re.compile(r"^[，。！？!?,.;；：:、\s]+|[，。！？!?,.;；：:、\s]+$")


def _normalize_action_text(text: str) -> str:
    normalized = text.strip().lower()
    normalized = _SPACE_RE.sub("", normalized)
    return _EDGE_PUNCTUATION_RE.sub("", normalized)


_ACTION_PHRASES: tuple[tuple[HandoffAction, frozenset[str]], ...] = (
    (HandoffAction.CLOSE, frozenset({"/close"})),
    (
        HandoffAction.CREATE_TICKET,
        frozenset({"建立工單", "建立派工單", "建工單", "開工單", "create ticket"}),
    ),
    (
        HandoffAction.CONTACT_HUMAN,
        frozenset(
            {
                "聯絡線上客服",
                "線上客服",
                "真人客服",
                "人工客服",
                "轉真人",
                "找真人",
                "contact human",
            }
        ),
    ),
    (
        HandoffAction.SUPPLEMENT,
        frozenset({"修改摘要", "繼續補充", "補充資料", "補充資訊", "重新產生摘要"}),
    ),
    (HandoffAction.CANCEL, frozenset({"取消", "不用了", "先不要", "cancel"})),
)


def parse_handoff_action(text: str) -> HandoffAction:
    """Recognise only deterministic, explicit Phase 2 commands.

    Exact phrase matching is deliberate.  Free text mentioning a command
    (for example, "不要建立工單") must not trigger a state transition.
    """

    normalized = _normalize_action_text(text)
    for action, phrases in _ACTION_PHRASES:
        if normalized in phrases:
            return action
    return HandoffAction.NONE


def is_explicit_human_request(text: str) -> bool:
    """Return whether the current turn explicitly requests human support."""
    normalized = _normalize_action_text(text)
    negative = ("不要", "不用", "不需要", "取消")
    phrases = ("真人客服", "人工客服", "線上客服", "轉真人", "找真人")
    return not any(item in normalized for item in negative) and any(
        item in normalized for item in phrases
    )


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


class ActiveCaseLookup(Protocol):
    async def get_active_case(
        self, tenant_id: str, conversation_id: str, requester_id: str
    ) -> Any | None: ...


@dataclass(frozen=True)
class HandoffDecision:
    handled: bool
    routing_target: RoutingTarget = RoutingTarget.AI_AGENT
    action: HandoffAction = HandoffAction.NONE
    answer: str | None = None
    case: Any | None = None
    should_save_message: bool = False
    should_close: bool = False

    @property
    def bypass_ai(self) -> bool:
        return self.handled and self.routing_target is RoutingTarget.HUMAN_DEMO


class HandoffRouter:
    """Read-only first-hop router used before the existing AI graph.

    Lifecycle mutations are intentionally delegated to the orchestrator or
    repository transaction layer.  The router's central guarantee is that a
    regular message in ``DEMO_ACTIVE`` is handled without invoking AI.
    """

    def __init__(self, repository: ActiveCaseLookup) -> None:
        self._repository = repository

    async def decide(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        requester_id: str,
        message: str,
    ) -> HandoffDecision:
        case = await self._repository.get_active_case(
            tenant_id, conversation_id, requester_id
        )
        if case is None:
            return HandoffDecision(handled=False, action=parse_handoff_action(message))

        status = _status_value(getattr(case, "status", None))
        action = parse_handoff_action(message)
        if status != "DEMO_ACTIVE":
            return HandoffDecision(
                handled=False,
                action=action,
                case=case,
                routing_target=RoutingTarget.AI_AGENT,
            )

        owner = str(getattr(case, "requesterId", ""))
        if action is HandoffAction.CLOSE:
            if owner != requester_id:
                return HandoffDecision(
                    handled=True,
                    routing_target=RoutingTarget.HUMAN_DEMO,
                    action=action,
                    answer=CLOSE_FORBIDDEN_MESSAGE,
                    case=case,
                )
            return HandoffDecision(
                handled=True,
                routing_target=RoutingTarget.HUMAN_DEMO,
                action=action,
                answer=DEMO_CLOSED_MESSAGE,
                case=case,
                should_close=True,
            )

        return HandoffDecision(
            handled=True,
            routing_target=RoutingTarget.HUMAN_DEMO,
            action=action,
            answer=DEMO_MESSAGE_SAVED,
            case=case,
            should_save_message=True,
        )


def offer_message(summary: SummaryDraft) -> str:
    return HANDOFF_OFFER_MESSAGE.format(summary=summary.render())
