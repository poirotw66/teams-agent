"""Pure generator retry-policy unit tests."""

from __future__ import annotations

from agent_service.contracts import GroundedClaim
from agent_service.knowledge_pipeline.generator import (
    is_unsupported_miss_answer,
    query_asks_for_error_branching,
    should_keep_prior_after_visual_retry,
    should_retry_error_coverage,
    should_retry_false_none,
    should_retry_procedure_coverage,
    should_retry_ticket_intake_coverage,
    should_retry_visual_evidence,
)


def test_should_retry_false_none_requires_high_confidence_and_lexical_overlap() -> None:
    assert not should_retry_false_none(
        answerability="NONE",
        results=[],
        confidence_label="HIGH_CONFIDENCE_PASS",
        answer="目前知識庫沒有足夠資訊",
        claims=[],
        resolved_issue_query="VPN 連不上",
    )


def test_should_retry_error_coverage_when_branches_missing() -> None:
    assert should_retry_error_coverage(
        answerability="FULL",
        resolved_issue_query="各錯誤碼分流怎麼處理",
        context_error_codes=["-455", "-500"],
        answer="請重試一次。",
    )
    assert query_asks_for_error_branching("錯誤碼分流")


def test_should_retry_procedure_and_visual_policies() -> None:
    assert should_retry_procedure_coverage(
        answerability="PARTIAL",
        resolved_issue_query="安裝步驟順序",
        context_procedure_steps=["intune_company_portal", "qr_code_scan"],
        answer="請依照手冊操作。",
    )
    assert should_retry_visual_evidence(
        answerability="FULL",
        resolved_issue_query="Visual Evidence 視覺順序",
        context_visual_plates=["p001", "p002"],
        answer="請看畫面。",
    )
    assert should_keep_prior_after_visual_retry(
        context_procedure_steps=["restart_outlook", "qr_code_scan"],
        answer="完成。",
    )


def test_should_retry_ticket_intake_when_short_script_omits_fields() -> None:
    assert should_retry_ticket_intake_coverage(
        answerability="FULL",
        resolved_issue_query="好麥系統解鎖",
        context_ticket_fields=[
            "requester_name",
            "employee_id",
            "haomai_account",
            "unlock_layer",
        ],
        answer="目前好麥系統尚未提供自助解鎖功能，此問題需由資訊人員協助進行帳號解鎖。",
    )
    assert not should_retry_ticket_intake_coverage(
        answerability="FULL",
        resolved_issue_query="VPN 連不上",
        context_ticket_fields=["requester_name", "employee_id"],
        answer="請改連公司 Wi-Fi。",
    )


def test_is_unsupported_miss_answer() -> None:
    assert is_unsupported_miss_answer(
        answer="目前知識庫沒有足夠資訊",
        answerability="NONE",
        claims=[],
    )
    assert not is_unsupported_miss_answer(
        answer="請重設密碼 [S1]",
        answerability="FULL",
        claims=[GroundedClaim(text="請重設密碼", chunkIds=["c1"])],
    )


def test_is_unsupported_miss_answer_rejects_padded_primary_gap() -> None:
    padded = (
        "目前知識庫中並未記載關於 BYOD 的正式政策條款編號。"
        "關於企業 App 的管控措施，請見安裝手冊 [S1]。"
    )
    assert is_unsupported_miss_answer(
        answer=padded,
        answerability="PARTIAL",
        claims=[GroundedClaim(text="安裝並登入即同意管控", chunkIds=["c1"])],
        resolved_issue_query="公司 BYOD 個人手機可安裝企業 App 的正式政策條款編號？",
    )
    # Leading miss with substantive claims that address the query stays allowed.
    leading_but_grounded = (
        "目前知識庫中並未記載例外流程。"
        "依 XQ 問題文件，報價異常可先確認是否為廠商問題 [S1]。"
    )
    assert not is_unsupported_miss_answer(
        answer=leading_but_grounded,
        answerability="PARTIAL",
        claims=[GroundedClaim(text="報價異常可先確認是否為廠商問題", chunkIds=["c1"])],
        resolved_issue_query="客戶說報價下單怪怪的要怎麼判斷是不是廠商問題",
    )
    # Scoped sub-detail gap with grounded main answer must remain allowed.
    scoped = "申請窗口為資訊處 [S1]。來源未特別說明緊急例外流程。"
    assert not is_unsupported_miss_answer(
        answer=scoped,
        answerability="PARTIAL",
        claims=[GroundedClaim(text="申請窗口為資訊處", chunkIds=["c1"])],
    )
    # Mid-answer primary-miss phrasing after a real answer must not refuse.
    mid_gap = (
        "依 XQ 問題文件，可先確認是否為廠商問題 [S1]。"
        "目前知識庫中並未記載其他例外流程。"
    )
    assert not is_unsupported_miss_answer(
        answer=mid_gap,
        answerability="PARTIAL",
        claims=[GroundedClaim(text="可先確認是否為廠商問題", chunkIds=["c1"])],
    )


def test_is_unsupported_miss_answer_rejects_underspecified_system_guess() -> None:
    assert is_unsupported_miss_answer(
        answer="針對 Gitlab 系統，負責單位為資訊管理處 [S1]。",
        answerability="PARTIAL",
        claims=[GroundedClaim(text="Gitlab 負責單位為資訊管理處", chunkIds=["c1"])],
        resolved_issue_query="那個系統昨天掛了要找誰",
    )
    assert not is_unsupported_miss_answer(
        answer="Gitlab 負責單位為資訊管理處 [S1]。",
        answerability="FULL",
        claims=[GroundedClaim(text="Gitlab 負責單位為資訊管理處", chunkIds=["c1"])],
        resolved_issue_query="Gitlab 掛了要找誰",
    )
    # Comparison questions that ask which system a credential belongs to are
    # not underspecified referrals.
    assert not is_unsupported_miss_answer(
        answer="AD 密碼適用於 VPN；入口網密碼連動金控網站帳密 [S1][S2]。",
        answerability="FULL",
        claims=[
            GroundedClaim(text="AD 密碼適用於 VPN", chunkIds=["c1"]),
            GroundedClaim(text="入口網密碼連動金控網站帳密", chunkIds=["c2"]),
        ],
        resolved_issue_query="AD、入口網、金控入口網密碼各屬哪個系統",
    )
