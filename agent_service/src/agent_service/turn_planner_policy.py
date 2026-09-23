"""Conditional Turn Planner activation policy."""

from __future__ import annotations

import re
from collections.abc import Sequence

_CONTEXTUAL_REPLY_PATTERN = re.compile(
    r"(那|這個|剛才|上面|剛才那個|一樣|同上|繼續|還有嗎|然後呢)",
)
_REFERENTIAL_PREFIX = re.compile(r"^(那|這個|剛才|上面)")


def resolve_turn_planner_mode(
    *,
    turn_planner_mode: str | None,
    turn_planner_enabled: bool,
) -> str:
    """Normalize mode; ``TURN_PLANNER_MODE`` wins over the legacy boolean."""
    mode = str(turn_planner_mode or "").strip().upper()
    if mode in {"OFF", "CONTEXTUAL", "ALL"}:
        return mode
    return "ALL" if turn_planner_enabled else "OFF"


def should_use_turn_planner(
    *,
    message: str,
    pending_clarification: bool,
    recent_turns: Sequence[str],
    has_pending_ticket_offer: bool,
) -> bool:
    """Return whether CONTEXTUAL mode should invoke the Turn Planner."""
    text = str(message or "").strip()
    if pending_clarification:
        return True
    if has_pending_ticket_offer:
        return True
    if not recent_turns:
        return False
    if _CONTEXTUAL_REPLY_PATTERN.search(text):
        return True
    if len(text) <= 12:
        return True
    return bool(_REFERENTIAL_PREFIX.match(text))


def should_invoke_turn_planner(
    *,
    mode: str,
    message: str,
    pending_clarification: bool,
    recent_turns: Sequence[str],
    has_pending_ticket_offer: bool,
) -> bool:
    normalized = resolve_turn_planner_mode(
        turn_planner_mode=mode,
        turn_planner_enabled=False,
    )
    if normalized == "OFF":
        return False
    if normalized == "ALL":
        return True
    return should_use_turn_planner(
        message=message,
        pending_clarification=pending_clarification,
        recent_turns=recent_turns,
        has_pending_ticket_offer=has_pending_ticket_offer,
    )


__all__ = [
    "resolve_turn_planner_mode",
    "should_invoke_turn_planner",
    "should_use_turn_planner",
]
