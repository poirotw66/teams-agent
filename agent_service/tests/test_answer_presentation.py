"""Tests for deterministic knowledge-answer presentation."""

from __future__ import annotations

from agent_service.answer_presentation import format_knowledge_answer_display


def test_format_vpn_password_expiry_dense_blob_into_lists() -> None:
    raw = (
        "若遇到三個月密碼到期，請插上實體網路線，使用 Ctrl + Alt + Delete "
        "變更公司電腦開機密碼 [S1]。若您使用的是內網型筆電，請直接更改密碼，"
        "不要前往金控入口網同步開機密碼 (AD) [S2]。"
    )
    formatted = format_knowledge_answer_display(raw)
    assert "請依下列步驟處理：" in formatted
    assert "1. 請插上實體網路線" in formatted
    assert "2. 使用 **Ctrl + Alt + Delete** 變更公司電腦開機密碼 [S1]" in formatted
    assert "若您使用的是內網型筆電，請依下列步驟處理：" in formatted
    assert "1. 請直接更改密碼" in formatted
    assert "2. 不要前往金控入口網同步開機密碼 (AD) [S2]" in formatted
    assert "\n\n" in formatted


def test_format_leaves_single_condition_sentence_unchanged() -> None:
    raw = "若網路不穩，請更換熱點後再試 [S1]。"
    assert format_knowledge_answer_display(raw) == raw
