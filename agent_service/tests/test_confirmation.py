"""Tests for the explicit ticket-confirmation detector (spec §11.3, §18.5)."""

import pytest

from agent_service.confirmation import (
    TicketIntent,
    classify_ticket_intent,
    is_explicit_ticket_confirmation,
    is_pending_ticket_offer_confirmation,
)

# Spec §11.3: these MUST be treated as explicit confirmation.
AFFIRMATIVE_EXAMPLES = [
    "請幫我建立工單",
    "好，幫我開單",
    "我要報修",
]

# Spec §11.3: these MUST NOT be treated as confirmation.
NON_CONFIRMATION_EXAMPLES = [
    "還是不能用",
    "好像需要找人",
    "可能要報修",
    "不知道怎麼辦",
]

NEGATION_EXAMPLES = [
    "不用開單",
    "先不要開單",
    "不要建立工單",
    "暫時不用報修",
]

EXTRA_AFFIRMATIVE_VARIANTS = [
    "麻煩幫我建立工單",
    "請開一張工單",
    "確定建立工單",
    "確認建立工單",
    "幫我建立工單，謝謝",
    "請開工單",
    "請協助建立派工單",
    "幫我建立派工單",
    "我要建立派工單",
    "請幫我開工單",
    "幫我開工單",
    "開工單",
    "請協助我開工單",
    "麻煩報修",
    "我要開單",
    "請報修",
    "幫忙建立工單",
]

EXTRA_NON_CONFIRMATION_VARIANTS = [
    "或許需要報修",
    "也許要開單",
    "大概要建立工單吧",
    "是不是要報修",
    "要不要開單",
    "需不需要建立工單",
    "應該要報修吧",
    "不確定要不要報修",
    "這樣算不算需要開單",
    "我不知道要不要建立工單",
]


@pytest.mark.parametrize("text", AFFIRMATIVE_EXAMPLES)
def test_spec_affirmative_examples_are_confirmations(text: str) -> None:
    assert is_explicit_ticket_confirmation(text) is True


@pytest.mark.parametrize("text", NON_CONFIRMATION_EXAMPLES)
def test_spec_non_confirmation_examples_are_rejected(text: str) -> None:
    assert is_explicit_ticket_confirmation(text) is False


@pytest.mark.parametrize("text", NEGATION_EXAMPLES)
def test_negations_are_rejected(text: str) -> None:
    assert is_explicit_ticket_confirmation(text) is False


@pytest.mark.parametrize("text", EXTRA_AFFIRMATIVE_VARIANTS)
def test_extra_affirmative_variants(text: str) -> None:
    assert is_explicit_ticket_confirmation(text) is True


@pytest.mark.parametrize("text", EXTRA_NON_CONFIRMATION_VARIANTS)
def test_extra_hedge_variants_are_rejected(text: str) -> None:
    assert is_explicit_ticket_confirmation(text) is False


def test_empty_and_unrelated_text_is_not_confirmation() -> None:
    assert is_explicit_ticket_confirmation("") is False
    assert is_explicit_ticket_confirmation("   ") is False
    assert is_explicit_ticket_confirmation("今天天氣如何？") is False
    assert is_explicit_ticket_confirmation("我的密碼是多少") is False


def test_hedge_vetoes_even_when_affirmative_pattern_present() -> None:
    # "可能要報修" contains the affirmative substring "報修" but must be
    # vetoed by the hedge marker "可能" per spec §11.3.
    text = "可能要報修"
    assert is_explicit_ticket_confirmation(text) is False
    assert "報修" in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("刪除工單後建立工單", TicketIntent.DELETE_DENIED),
        ("不知道，先不要建立工單", TicketIntent.CANCEL),
        ("不要開單，幫我查詢我的工單", TicketIntent.CANCEL),
        ("請建立工單後查詢我的工單", TicketIntent.QUERY),
        ("VPN Error 619，請建立工單", TicketIntent.CREATE),
        ("是", TicketIntent.NONE),
    ],
)
def test_ticket_intent_has_fixed_cancel_query_create_none_priority(
    text: str, expected: TicketIntent
) -> None:
    assert classify_ticket_intent(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "有哪些工單",
        "有哪些派工單",
        "我的工單進度如何？",
        "我的派工單進度如何？",
    ],
)
def test_ticket_list_and_progress_queries_are_classified_deterministically(
    text: str,
) -> None:
    assert classify_ticket_intent(text) == TicketIntent.QUERY


@pytest.mark.parametrize("text", ["是", "是。", "好", "好的！", "可以", "確認", "<是>", "「是」"])
def test_pending_offer_accepts_only_short_confirmations(text: str) -> None:
    assert is_pending_ticket_offer_confirmation(text) is True


@pytest.mark.parametrize("text", ["不是", "不知道", "可能", "再看看", "先不要"])
def test_pending_offer_rejects_ambiguous_or_negative_replies(text: str) -> None:
    assert is_pending_ticket_offer_confirmation(text) is False


@pytest.mark.parametrize(
    "text",
    ["請協助建立派工單", "VPN Error 619，請建立派工單", "幫我開一張派工單"],
)
def test_dispatch_ticket_phrases_classify_as_create(text: str) -> None:
    assert classify_ticket_intent(text) == TicketIntent.CREATE
    assert is_explicit_ticket_confirmation(text) is True
