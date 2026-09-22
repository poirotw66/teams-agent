"""Tests for service-scope evidence and NOT_IT / NON_IT veto paths."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_service.confirmation import TicketIntent, classify_ticket_intent
from agent_service.contracts import (
    AgentRequest,
    ConversationIdentity,
    Issue,
    MessageContent,
    UserIdentity,
)
from agent_service.extractor_normalizer import coerce_issue, postprocess_issues
from agent_service.response_builder import ALL_NON_IT_MESSAGE
from agent_service.service_scope_evidence import (
    EXPECTED_RELEASE_TITLES_FOR_SCOPE,
    configure_service_scope_from_documents,
    configure_service_scope_from_manifest,
    find_service_scope_hits,
    has_service_scope_evidence,
    is_complete_service_scope_query,
    missing_expected_release_titles,
    reset_service_scope_catalog,
)
from agent_service.supervisor import ConversationSupervisorDecision
from agent_service.turn_planner import PlannedIssue, planned_issues_to_issues
from agent_service.workflow_clarification import ClarificationWorkflowMixin


@pytest.fixture(autouse=True)
def _reset_service_scope_catalog() -> None:
    reset_service_scope_catalog()
    yield
    reset_service_scope_catalog()


def _issue(**overrides: object) -> Issue:
    base: dict = {
        "id": 1,
        "description": "天氣如何",
        "isIT": False,
        "readiness": "NOT_IT",
        "missingInfo": [],
        "route": "NOT_IT",
        "faqKey": None,
        "ticketAction": None,
    }
    base.update(overrides)
    return Issue(**base)


def _request(text: str) -> AgentRequest:
    return AgentRequest(
        requestId="req-scope-1",
        channel="msteams",
        conversation=ConversationIdentity(tenantId="tenant-1", conversationId="conv-1"),
        user=UserIdentity(entraObjectId="user-1", displayName="Alice"),
        message=MessageContent(text=text, locale="zh-TW"),
    )


@pytest.mark.parametrize(
    "text",
    [
        "座位遷移需求",
        "座位遷移準則",
        "座位搬遷",
        "換座位怎麼申請",
        "電腦聯繫單格式",
    ],
)
def test_seat_aliases_are_in_scope_evidence(text: str) -> None:
    assert has_service_scope_evidence(text) is True
    assert is_complete_service_scope_query(text) is True


@pytest.mark.parametrize(
    "text",
    ["今天天氣如何", "午餐吃什麼", "早餐推薦"],
)
def test_true_oos_has_no_scope_evidence(text: str) -> None:
    assert has_service_scope_evidence(text) is False


def test_static_fallback_works_without_governed_overlay() -> None:
    reset_service_scope_catalog()
    assert has_service_scope_evidence("座位遷移") is True
    assert has_service_scope_evidence("今天天氣如何") is False


def test_manifest_aliases_are_used_when_configured(tmp_path: Path) -> None:
    manifest = {
        "releaseId": "release-test",
        "documents": [
            {
                "document_id": "doc-seat",
                "title": "座位搬遷需求",
                "source_aliases": ["座位遷移", "換座位", "電腦聯繫單", "座位調度試驗別名"],
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert configure_service_scope_from_manifest(path) == 1
    assert has_service_scope_evidence("座位調度試驗別名") is True
    hits = find_service_scope_hits("座位調度試驗別名怎麼申請")
    assert len(hits) == 1
    assert hits[0].service_id == "seat_relocation"
    assert hits[0].canonical_title == "座位搬遷需求"
    # Static fallback aliases remain after merge.
    assert has_service_scope_evidence("電腦聯絡單") is True
    # True OOS must not match.
    assert has_service_scope_evidence("今天天氣如何") is False


def test_manifest_extra_document_aliases_extend_catalog() -> None:
    configure_service_scope_from_documents(
        [
            {
                "document_id": "doc-vpn-demo",
                "title": "Demo VPN Guide",
                "source_aliases": ["FortiClient 試驗別名"],
            }
        ]
    )
    assert has_service_scope_evidence("FortiClient 試驗別名無法連線") is True
    assert has_service_scope_evidence("座位遷移") is True
    assert has_service_scope_evidence("今天天氣如何") is False


def test_empty_manifest_aliases_keep_static_catalog(tmp_path: Path) -> None:
    manifest = {
        "releaseId": "release-empty",
        "documents": [
            {
                "document_id": "doc-seat",
                "title": "座位搬遷需求",
                "source_aliases": [],
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert configure_service_scope_from_manifest(path) == 0
    assert has_service_scope_evidence("換座位") is True
    assert has_service_scope_evidence("今天天氣如何") is False


@pytest.mark.parametrize(
    "utterance",
    ["座位遷移需求", "座位遷移準則", "座位搬遷"],
)
def test_coerce_seat_query_vetoes_not_it_and_is_ready(utterance: str) -> None:
    coerced = coerce_issue(
        _issue(description=utterance, isIT=False, readiness="NOT_IT", route="NOT_IT"),
        new_id=1,
        allowed_faq_keys=set(),
        max_missing_info=2,
        raw_utterance=utterance,
    )
    assert coerced.isIT is True
    assert coerced.readiness == "READY"
    assert coerced.route == "KNOWLEDGE"
    assert coerced.missingInfo == []
    assert "不屬於公司 IT 支援範圍" not in (coerced.description or "")
    assert ALL_NON_IT_MESSAGE not in (coerced.description or "")


def test_coerce_does_not_force_system_clarification_for_seat_doc_query() -> None:
    coerced = coerce_issue(
        _issue(
            description="座位遷移準則",
            isIT=False,
            readiness="NOT_IT",
            route="NOT_IT",
            missingInfo=["請確認您希望查詢的系統與處理面向。"],
        ),
        new_id=1,
        allowed_faq_keys=set(),
        max_missing_info=2,
        raw_utterance="座位遷移準則",
    )
    assert coerced.readiness == "READY"
    assert coerced.missingInfo == []


def test_supervisor_high_confidence_non_it_does_not_skip_when_seat_in_scope() -> None:
    mixin = ClarificationWorkflowMixin()
    mixin.settings = SimpleNamespace(supervisor_terminal_confidence=0.85)
    mixin.supervisor = SimpleNamespace(
        supports_terminal_intent=lambda _message, _intent: True
    )
    conversation = SimpleNamespace(pendingIssues=[], messages=[])
    decision = ConversationSupervisorDecision(intent="NON_IT", confidence=0.99)
    routing = mixin._apply_supervisor_routing(
        conversation,
        _request("座位遷移需求"),
        decision,
    )
    assert routing.get("skip_issue_pipeline") is not True
    assert "issues" not in routing or routing.get("issues") is None


def test_supervisor_non_it_still_skips_for_true_oos() -> None:
    mixin = ClarificationWorkflowMixin()
    mixin.settings = SimpleNamespace(supervisor_terminal_confidence=0.85)
    mixin.supervisor = SimpleNamespace(
        supports_terminal_intent=lambda _message, _intent: True
    )
    conversation = SimpleNamespace(pendingIssues=[], messages=[])
    decision = ConversationSupervisorDecision(intent="NON_IT", confidence=0.99)
    routing = mixin._apply_supervisor_routing(
        conversation,
        _request("今天天氣如何"),
        decision,
    )
    assert routing.get("skip_issue_pipeline") is True
    assert routing["issues"][0].route == "NOT_IT"


def test_ticket_query_with_seat_relocation_keeps_ticket_path() -> None:
    message = "查詢座位搬遷工單"
    assert classify_ticket_intent(message) is TicketIntent.QUERY
    mixin = ClarificationWorkflowMixin()
    mixin.settings = SimpleNamespace(supervisor_terminal_confidence=0.85)
    mixin.supervisor = SimpleNamespace(
        supports_terminal_intent=lambda _message, _intent: True
    )
    conversation = SimpleNamespace(pendingIssues=[], messages=[])
    # Even if supervisor mislabels NON_IT, deterministic ticket intent wins and
    # scope evidence blocks skip — ticket QUERY remains in routing.
    decision = ConversationSupervisorDecision(intent="NON_IT", confidence=0.99)
    routing = mixin._apply_supervisor_routing(conversation, _request(message), decision)
    assert routing.get("ticket_intent") is TicketIntent.QUERY
    assert routing.get("skip_issue_pipeline") is not True


def test_mixed_seat_and_lunch_keeps_it_issue_only() -> None:
    issues, _too_many = postprocess_issues(
        [
            _issue(
                id=1,
                description="座位遷移需求",
                isIT=False,
                readiness="NOT_IT",
                route="NOT_IT",
            ),
            _issue(
                id=2,
                description="午餐吃什麼",
                isIT=False,
                readiness="NOT_IT",
                route="NOT_IT",
            ),
        ],
        faq_keys=[],
        max_issues=3,
        max_missing_info=2,
        raw_utterance="座位遷移需求，另外午餐吃什麼",
    )
    assert len(issues) == 2
    seat, lunch = issues
    assert seat.isIT is True
    assert seat.readiness == "READY"
    assert seat.route == "KNOWLEDGE"
    assert lunch.isIT is False
    assert lunch.readiness == "NOT_IT"
    assert lunch.route == "NOT_IT"


def test_true_oos_weather_and_breakfast_remain_not_it() -> None:
    for utterance in ("今天天氣如何", "早餐推薦"):
        coerced = coerce_issue(
            _issue(description=utterance),
            new_id=1,
            allowed_faq_keys=set(),
            max_missing_info=2,
            raw_utterance=utterance,
        )
        assert coerced.isIT is False
        assert coerced.readiness == "NOT_IT"
        assert coerced.route == "NOT_IT"


def test_turn_planner_planned_issues_normalize_seat_not_it() -> None:
    issues = planned_issues_to_issues(
        [
            PlannedIssue(
                description="座位遷移準則",
                isIT=False,
                readiness="NOT_IT",
                route="NOT_IT",
            )
        ],
        raw_utterance="座位遷移準則",
        allowed_faq_keys=set(),
        max_missing_info=2,
    )
    assert len(issues) == 1
    assert issues[0].isIT is True
    assert issues[0].readiness == "READY"
    assert issues[0].route == "KNOWLEDGE"


def test_missing_expected_release_titles_helper() -> None:
    assert "座位搬遷需求" in EXPECTED_RELEASE_TITLES_FOR_SCOPE
    missing = missing_expected_release_titles(["VPN常見Q&A問答", "AD 帳號與系統解鎖 FAQ"])
    assert missing == ["座位搬遷需求"]
    assert missing_expected_release_titles(["座位搬遷需求", "VPN常見Q&A問答"]) == []
