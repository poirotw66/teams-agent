"""Tests for the explicit ticket-confirmation detector (spec §11.3, §18.5)."""

import pytest

from agent_service.confirmation import is_explicit_ticket_confirmation

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
