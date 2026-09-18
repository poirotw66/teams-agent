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
