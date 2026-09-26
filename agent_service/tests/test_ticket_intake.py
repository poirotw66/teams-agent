"""Ticket-intake coverage for unlock / dispatch answers."""

from __future__ import annotations

from agent_service.knowledge_pipeline.ticket_intake import (
    answer_covers_ticket_intake_fields,
    missing_ticket_intake_fields,
    query_asks_for_ticket_intake,
    ticket_intake_fields_in_text,
)

_HAOMAI_CONTEXT = """
建立工單前資訊確認
1. 使用者姓名
2. 員工編號
3. 好麥帳號
4. 需解鎖層數(第一層/第二層)
5. 問題描述
6. 如有錯誤畫面，可請使用者提供截圖
"""

_SHORT_SCRIPT = (
    "目前好麥系統尚未提供自助解鎖功能，此問題需由資訊人員協助進行帳號解鎖。"
    "如需要，我可以協助將此問題轉派工單由資訊人員處理。"
)

_DETAILED_ANSWER = """
目前好麥系統尚未提供自助解鎖功能，需由資訊人員協助解鎖。建立工單前請確認：
1. 使用者姓名
2. 員工編號
3. 好麥帳號
4. 解鎖層數（第一層／第二層）
5. 問題描述
6. 錯誤畫面截圖
"""


def test_query_asks_for_ticket_intake_on_unlock() -> None:
    assert query_asks_for_ticket_intake("好麥系統解鎖")
    assert query_asks_for_ticket_intake("請幫我解鎖好麥")
    assert not query_asks_for_ticket_intake("VPN 連不上")


def test_short_unlock_script_omits_ticket_fields() -> None:
    fields = ticket_intake_fields_in_text(_HAOMAI_CONTEXT)
    assert fields == [
        "requester_name",
        "employee_id",
        "haomai_account",
        "unlock_layer",
        "problem_description",
        "error_evidence",
    ]
    assert not answer_covers_ticket_intake_fields(_SHORT_SCRIPT, fields)
    assert "requester_name" in missing_ticket_intake_fields(_SHORT_SCRIPT, fields)
    assert "employee_id" in missing_ticket_intake_fields(_SHORT_SCRIPT, fields)


def test_detailed_unlock_answer_covers_ticket_fields() -> None:
    fields = ticket_intake_fields_in_text(_HAOMAI_CONTEXT)
    assert answer_covers_ticket_intake_fields(_DETAILED_ANSWER, fields)
    assert missing_ticket_intake_fields(_DETAILED_ANSWER, fields) == []
