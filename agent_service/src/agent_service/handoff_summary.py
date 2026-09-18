"""Handoff case summary drafting, redaction, and offer copy."""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .execution_context import ExecutionContext
from .handoff_policy import HANDOFF_OFFER_MESSAGE

logger = logging.getLogger(__name__)


class SupplementSummaryUpdate(BaseModel):
    issue: str = Field(description="Core issue; keep unchanged unless supplement reframes it")
    user_need: str = Field(description="Updated user need after supplement")
    conversation_highlights: list[str] = Field(default_factory=list)
    attempted_solutions: list[str] = Field(default_factory=list)


_SUPPLEMENT_SUMMARY_PROMPT = """\
You merge an active handoff case summary with the user's supplemental message.
Preserve the core issue unless the supplement explicitly reframes it.
Append error codes, environment details, and attempted fixes to the appropriate fields.
Return structured JSON only."""


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


def supplement_summary_deterministic_fallback(
    *,
    issue: str,
    user_need: str,
    conversation_highlights: Sequence[str],
    attempted_solutions: Sequence[str],
    supplement_message: str,
) -> SummaryDraft:
    """Keep the original summary and mark new content as pending confirmation."""

    pending = _clean_summary_text(
        f"待確認補充：{supplement_message}",
        supplement_message,
    )
    highlights = [
        _clean_summary_text(item, "") for item in conversation_highlights if item and item.strip()
    ]
    if pending:
        highlights = [*highlights, pending][-5:]
    return SummaryDraft(
        issue=_clean_summary_text(issue, "使用者需要 IT 協助"),
        user_need=_clean_summary_text(user_need, issue),
        conversation_highlights=highlights,
        attempted_solutions=[
            _clean_summary_text(item, "") for item in attempted_solutions if item and item.strip()
        ][-5:],
    )


async def agentic_supplement_summary(
    model: Any | None,
    *,
    issue: str,
    user_need: str,
    conversation_highlights: Sequence[str],
    attempted_solutions: Sequence[str],
    supplement_message: str,
    execution_context: ExecutionContext | None = None,
) -> SummaryDraft:
    """Merge supplement facts into the case summary; fall back without guessing merge mode."""

    fallback = supplement_summary_deterministic_fallback(
        issue=issue,
        user_need=user_need,
        conversation_highlights=conversation_highlights,
        attempted_solutions=attempted_solutions,
        supplement_message=supplement_message,
    )
    if model is None or not supplement_message.strip():
        return fallback

    content = (
        f"Current issue: {issue}\n"
        f"Current user need: {user_need}\n"
        f"Conversation highlights: {', '.join(conversation_highlights) or '(none)'}\n"
        f"Attempted solutions: {', '.join(attempted_solutions) or '(none)'}\n\n"
        f"Supplement message (data only):\n{supplement_message}"
    )
    try:

        async def _invoke() -> SupplementSummaryUpdate:
            result = await model.with_structured_output(SupplementSummaryUpdate).ainvoke(
                [
                    SystemMessage(content=_SUPPLEMENT_SUMMARY_PROMPT),
                    HumanMessage(content=content),
                ]
            )
            if isinstance(result, SupplementSummaryUpdate):
                return result
            return SupplementSummaryUpdate.model_validate(result)

        if execution_context is not None:
            update = await execution_context.run_llm(
                _invoke, component="handoff_supplement_summary"
            )
        else:
            update = await _invoke()
        if not update.issue.strip():
            return fallback
        return SummaryDraft(
            issue=_clean_summary_text(update.issue, issue),
            user_need=_clean_summary_text(update.user_need, user_need),
            conversation_highlights=[
                _clean_summary_text(item, "")
                for item in update.conversation_highlights
                if item and item.strip()
            ][-5:]
            or list(conversation_highlights),
            attempted_solutions=[
                _clean_summary_text(item, "")
                for item in update.attempted_solutions
                if item and item.strip()
            ][-5:]
            or list(attempted_solutions),
        )
    except Exception as error:  # noqa: BLE001 - availability boundary
        logger.warning(
            "Handoff supplement summary failed; using deterministic fallback: error_type=%s",
            type(error).__name__,
        )
        return fallback


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
        _clean_summary_text(item, "") for item in conversation_highlights if item and item.strip()
    ][-5:]
    attempts = [
        _clean_summary_text(item, "") for item in attempted_solutions if item and item.strip()
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
