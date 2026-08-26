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

from enum import Enum


class TicketIntent(str, Enum):
    """The ticket operation requested by the current message.

    This intentionally small, deterministic taxonomy is a safety boundary for
    side-effecting ticket operations.  It is not an LLM classification: every
    caller receives the same result for the same text.
    """

    DELETE_DENIED = "DELETE_DENIED"
    CANCEL = "CANCEL"
    QUERY = "QUERY"
    CREATE = "CREATE"
    NONE = "NONE"

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
    "建立派工單",
    "建工單",
    "建派工單",
    "建單",
    "開單",
    "報修",
    "開一張工單",
    "開一張派工單",
    "開個工單",
    "開個派工單",
    "開張工單",
    "開張派工單",
    "提交工單",
    "提交派工單",
    "送出工單",
    "送出派工單",
    "申請工單",
    "申請派工單",
    "幫我開單",
    "幫我報修",
    "幫我建立工單",
    "幫我建立派工單",
    "幫忙建立工單",
    "幫忙建立派工單",
    "確認建立工單",
    "確認建立派工單",
    "確定建立工單",
    "確定建立派工單",
    "我要報修",
    "我要開單",
    "我要建立工單",
    "我要建立派工單",
    "麻煩開單",
    "麻煩報修",
    "麻煩建立工單",
    "麻煩建立派工單",
    "好，幫我開單",
    "好,幫我開單",
    "好，開單",
    "請幫我建立工單",
    "請幫我建立派工單",
    "請協助建立工單",
    "請協助建立派工單",
    "請建立工單",
    "請建立派工單",
    "請開工單",
    "請開派工單",
    "請開單",
    "請報修",
    "協助建立工單",
    "協助建立派工單",
)

# Cancellation must be recognised as a ticket-specific request.  A generic
# "不要" in an otherwise valid IT question (for example, "不要要求密碼") is
# not a ticket cancellation, whereas "先不要建立工單" is.
_CANCEL_PATTERNS: tuple[str, ...] = (
    "取消工單",
    "取消派工單",
    "取消建立",
    "不要建立工單",
    "不要建立派工單",
    "不要建工單",
    "不要建派工單",
    "不要開工單",
    "不要開派工單",
    "不要開單",
    "不要報修",
    "先不要建立工單",
    "先不要建立派工單",
    "先不要建工單",
    "先不要建派工單",
    "先不要開工單",
    "先不要開派工單",
    "先不要開單",
    "先不要報修",
    "先不建立工單",
    "先不建立派工單",
    "先不開單",
    "先不報修",
    "不用建立工單",
    "不用建立派工單",
    "不用開單",
    "不用報修",
    "不必建立工單",
    "不必建立派工單",
    "不必開單",
    "不必報修",
    "暫時不要建立工單",
    "暫時不要建立派工單",
    "暫時不要開單",
    "暫時不要報修",
    "不需要建立工單",
    "不需要建立派工單",
    "不需要開單",
    "不需要報修",
)

_DELETE_PATTERNS: tuple[str, ...] = (
    "刪除工單",
    "刪除派工單",
    "刪掉工單",
    "刪掉派工單",
    "刪工單",
    "刪派工單",
    "移除工單",
    "移除派工單",
)

_QUERY_MARKERS: tuple[str, ...] = (
    "查詢",
    "查一下",
    "查查",
    "查看",
    "檢視",
    "列出",
    "進度",
    "狀態",
    "列表",
    "追蹤",
)

_PENDING_OFFER_CONFIRMATIONS: tuple[str, ...] = (
    "是",
    "好",
    "好的",
    "可以",
    "確認",
    "確定",
)


def classify_ticket_intent(text: str) -> TicketIntent:
    """Classify the ticket intent with a fixed, auditable precedence.

    The priority is deliberately
    ``DELETE_DENIED > CANCEL > QUERY > CREATE > NONE``.  In
    particular, a cancellation wins even when the text also includes an old
    affirmative phrase, preventing a pending offer or an LLM route from
    reopening a ticket request the user just withdrew.
    """
    normalized = text.strip()
    if not normalized:
        return TicketIntent.NONE

    if any(pattern in normalized for pattern in _DELETE_PATTERNS):
        return TicketIntent.DELETE_DENIED
    if any(pattern in normalized for pattern in _CANCEL_PATTERNS):
        return TicketIntent.CANCEL
    mentions_ticket = "工單" in normalized or "派工單" in normalized
    if mentions_ticket and any(marker in normalized for marker in _QUERY_MARKERS):
        return TicketIntent.QUERY
    if is_explicit_ticket_confirmation(normalized):
        return TicketIntent.CREATE
    return TicketIntent.NONE


def is_pending_ticket_offer_confirmation(text: str) -> bool:
    """Accept a short confirmation only when the workflow has a live offer."""
    normalized = text.strip().rstrip("。.!！")
    # Allow wrappers used in the offer copy, e.g. <是> or 「是」.
    normalized = normalized.strip("<>「」")
    return normalized in _PENDING_OFFER_CONFIRMATIONS


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
