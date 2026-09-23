"""Regression tests for clarification ERROR matching and FortiClient catalog UX."""

from __future__ import annotations

from agent_service.contracts import Issue, PendingIssueContext
from agent_service.workflow_clarification_helpers import (
    _answers_missing_info,
    _complete_complementary_pending_issue,
    _detail_satisfies_kind,
    _is_error_catalog_documentation_request,
    _promote_error_catalog_documentation_request,
)
from operations_core.default_extractor_prompt import SYSTEM_PROMPT


def test_extractor_prompt_marks_catalog_requests_ready() -> None:
    assert "Documentation / catalog requests are READY" in SYSTEM_PROMPT
    assert "錯訊說明" in SYSTEM_PROMPT
    assert "不要只給一般 VPN Q&A" in SYSTEM_PROMPT


def test_bare_digits_do_not_satisfy_error_clarification() -> None:
    assert not _detail_satisfies_kind("888", "ERROR")
    assert not _answers_missing_info(
        "888",
        ["請提供您在 FortiClient 上看到的具體錯誤訊息或錯誤代碼"],
    )


def test_signed_or_phrased_errors_satisfy_error_clarification() -> None:
    assert _detail_satisfies_kind("(-455)", "ERROR")
    assert _detail_satisfies_kind("-14", "ERROR")
    assert _detail_satisfies_kind("Permission denied (-455)", "ERROR")
    assert _answers_missing_info(
        "(-20199)",
        ["請提供您看到的具體錯誤訊息或錯誤代碼"],
    )


def test_forticlient_catalog_request_detection() -> None:
    assert _is_error_catalog_documentation_request(
        "FortiClient 錯訊說明，不要只給一般 VPN Q&A"
    )
    assert _is_error_catalog_documentation_request(
        "ortiClient 錯訊說明，不要只給一般 VPN Q&A"
    )
    assert _is_error_catalog_documentation_request("其他的錯誤碼呢？")
    assert not _is_error_catalog_documentation_request("VPN 連不上")


def test_promote_catalog_request_forces_ready_knowledge() -> None:
    issue = Issue(
        id=1,
        description="詢問 FortiClient 錯誤訊息",
        isIT=True,
        readiness="NEED_MORE_INFO",
        missingInfo=["請提供具體錯誤代碼"],
        route="KNOWLEDGE",
    )
    latest = "FortiClient 錯訊說明，不要只給一般 VPN Q&A"
    promoted = _promote_error_catalog_documentation_request([issue], latest)
    assert len(promoted) == 1
    assert promoted[0].readiness == "READY"
    assert promoted[0].missingInfo == []
    assert promoted[0].description == latest
    assert promoted[0].retrieval_query == latest


def test_complete_complementary_does_not_merge_bare_digits_into_catalog_pending() -> None:
    pending = PendingIssueContext(
        description="FortiClient 錯訊說明，不要只給一般 VPN Q&A",
        contextText="FortiClient 錯訊說明，不要只給一般 VPN Q&A",
        route="KNOWLEDGE",
        missingInfo=["請提供您在 FortiClient 上看到的具體錯誤訊息或錯誤代碼"],
        clarificationCount=1,
    )
    issue = Issue(
        id=1,
        description="補充錯誤代碼",
        isIT=True,
        readiness="NEED_MORE_INFO",
        missingInfo=["請提供系統名稱"],
        route="KNOWLEDGE",
    )
    result = _complete_complementary_pending_issue([issue], [pending], "888")
    assert result[0].readiness == "NEED_MORE_INFO"
    assert "888" not in (result[0].description or "")


def test_complete_complementary_promotes_catalog_reask_over_pending() -> None:
    pending = PendingIssueContext(
        description="FortiClient 錯訊說明",
        contextText="FortiClient 錯訊說明，不要只給一般 VPN Q&A",
        route="KNOWLEDGE",
        missingInfo=["請提供您看到的具體錯誤訊息或錯誤代碼"],
        clarificationCount=1,
    )
    issue = Issue(
        id=1,
        description="仍缺錯誤碼",
        isIT=True,
        readiness="NEED_MORE_INFO",
        missingInfo=["請提供具體錯誤代碼"],
        route="KNOWLEDGE",
    )
    latest = "FortiClient 錯訊說明，不要只給一般 VPN Q&A"
    result = _complete_complementary_pending_issue([issue], [pending], latest)
    assert result[0].readiness == "READY"
    assert result[0].missingInfo == []
    assert "888" not in result[0].description
    assert "錯訊說明" in result[0].description
