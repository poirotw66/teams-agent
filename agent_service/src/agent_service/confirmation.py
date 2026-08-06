"""Explicit ticket-creation confirmation detector (spec §11.3).

Spec §11.3: 未經明確確認，不得建立工單 — a ticket may only be created after
the user has EXPLICITLY confirmed it. This module implements that check
deterministically (no LLM call), per spec §16's guidance to avoid
unnecessary LLM calls and because a creation gate must be predictable and
auditable rather than probabilistic.

Design
------
Two static pattern lists, evaluated **veto-first**:

1. ``_HEDGE_MARKERS`` / ``_NEGATION_MARKERS`` — hedging or negating words
   (可能/好像/也許/或許/大概/不知道/是不是/要不要/需不需要/應該/猜/算不算,
   and negations like 不用/不要/先不/不必/別/暫時不). If any of these appear
   anywhere in the message, the function returns ``False`` immediately,
   even if an affirmative pattern also matches. This is deliberately
   conservative: e.g. "可能要報修" contains "報修" (an affirmative pattern)
   but the hedge "可能" must veto it, per spec §11.3's explicit example.
2. ``_AFFIRMATIVE_PATTERNS`` — substrings that, absent a veto, indicate an
   explicit request to create a ticket (e.g. 建立工單/開單/報修).

Only if no veto marker is present AND at least one affirmative pattern
matches does the function return ``True``.

Scope boundary
---------------
This module is strictly about detecting an explicit CONFIRMATION to
create a ticket. It does NOT classify "does the user want to query their
existing ticket" (a query intent) — that classification belongs to the
Issue Extractor, not here.
"""

from __future__ import annotations

# Hedging words: presence anywhere means the statement is not a firm,
# explicit confirmation (spec §11.3 non-confirmation examples such as
# "可能要報修").
_HEDGE_MARKERS: tuple[str, ...] = (
    "可能",
    "好像",
    "也許",
    "或許",
    "大概",
    "不知道",
    "是不是",
    "要不要",
    "需不需要",
    "應該",
    "猜",
    "不確定",
    "算不算",
)

# Negation words: presence anywhere means the user is declining/withdrawing
# a ticket request, not confirming one (e.g. "不用開單", "先不要開單").
_NEGATION_MARKERS: tuple[str, ...] = (
    "不用",
    "不要",
    "先不",
    "不必",
    "別",
    "暫時不",
    "還是不",
    "不需要",
)

# Affirmative patterns: explicit requests/agreement to create a ticket
# (spec §11.3 confirmation examples plus realistic Traditional Chinese
# variants).
_AFFIRMATIVE_PATTERNS: tuple[str, ...] = (
    "建立工單",
    "建工單",
    "建單",
    "開單",
    "報修",
    "開一張工單",
    "開個工單",
    "開張工單",
    "提交工單",
    "送出工單",
    "申請工單",
    "幫我開單",
    "幫我報修",
    "幫我建立工單",
    "幫忙建立工單",
    "確認建立工單",
    "確定建立工單",
    "我要報修",
    "我要開單",
    "我要建立工單",
    "麻煩開單",
    "麻煩報修",
    "麻煩建立工單",
    "好，幫我開單",
    "好,幫我開單",
    "好，開單",
    "請幫我建立工單",
    "請建立工單",
    "請開工單",
    "請開單",
    "請報修",
)


def is_explicit_ticket_confirmation(text: str) -> bool:
    """Return True iff ``text`` is an explicit confirmation to create a ticket.

    Deterministic substring matching, no LLM call. Veto markers (hedges,
    negations) are checked first and always win over an affirmative match.
    """
    normalized = text.strip()
    if not normalized:
        return False

    for marker in _HEDGE_MARKERS:
        if marker in normalized:
            return False
    for marker in _NEGATION_MARKERS:
        if marker in normalized:
            return False

    return any(pattern in normalized for pattern in _AFFIRMATIVE_PATTERNS)
