"""Tests for production-path AgentWorkflow evaluation contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_service.agent_workflow_eval import (
    AgentWorkflowEvalCase,
    aggregate_agent_workflow_scores,
    issue_routes_from_state,
    normalize_eval_route,
    observe_answer_found,
    observe_handoff_triggered,
    observe_ticket_triggered,
    routes_equivalent,
    score_agent_workflow_case,
)

EVAL_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "eval" / "agent_workflow_eval_v1.json"
)


def test_agent_workflow_eval_set_has_required_fields() -> None:
    payload = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    assert payload["caseCount"] == len(payload["cases"]) >= 3
    assert payload["freezeVersion"] >= 2
    route_counts: dict[str, int] = {}
    has_multi_turn = False
    has_greeting = False
    has_knowledge = False
    for raw in payload["cases"]:
        case = AgentWorkflowEvalCase.from_dict(raw)
        assert case.case_id
        assert case.message
        assert case.expected_route
        assert isinstance(case.forbidden_actions, tuple)
        route_counts[case.expected_route] = route_counts.get(case.expected_route, 0) + 1
        if case.prior_turns:
            has_multi_turn = True
        if case.expected_route == "GREETING":
            has_greeting = True
        if case.expected_route == "KNOWLEDGE":
            has_knowledge = True
    assert has_multi_turn and has_greeting and has_knowledge
    assert len(payload["cases"]) >= 10


def test_normalize_eval_route_maps_supervisor_it_support_to_knowledge() -> None:
    assert normalize_eval_route("IT_SUPPORT") == "KNOWLEDGE"
    assert normalize_eval_route("GREETING") == "GREETING"
    assert normalize_eval_route("NON_IT") == "NOT_IT"
    assert routes_equivalent("KNOWLEDGE", "IT_SUPPORT")
    assert routes_equivalent("KNOWLEDGE", "FAQ")
    assert not routes_equivalent("GREETING", "IT_SUPPORT")


def test_score_agent_workflow_case_aligns_supervisor_it_support_with_knowledge() -> None:
    case = AgentWorkflowEvalCase.from_dict(
        {
            "id": "workflow-v1-001",
            "message": "FortiClient 出現 -455 怎麼辦？",
            "expectedRoute": "KNOWLEDGE",
            "expectedIssueCount": 1,
            "expectedFound": True,
            "expectedDocuments": ["登入 FortiClient 出現錯訊"],
            "forbiddenActions": ["CREATE_TICKET", "HANDOFF"],
        }
    )
    score = score_agent_workflow_case(
        case=case,
        observed_route="IT_SUPPORT",
        observed_issue_count=1,
        observed_issue_routes=("KNOWLEDGE",),
        observed_found=True,
        cited_titles=("登入 FortiClient 出現錯訊", "noise"),
        ticket_triggered=True,
        handoff_triggered=False,
        llm_calls=2,
        latency_ms=1200.0,
    )
    assert score.supervisor_route_match == 1.0
    assert score.issue_route_match == 1.0
    assert score.issue_count_match == 1.0
    assert score.answer_found_match == 1.0
    assert score.citation_precision == 0.5
    assert score.citation_recall == 1.0
    assert score.ticket_false_trigger == 1.0
    assert score.handoff_false_trigger == 0.0
    summary = aggregate_agent_workflow_scores([score])
    assert summary["caseCount"] == 1.0
    assert summary["supervisorRouteAccuracy"] == 1.0
    assert summary["ticketFalseTriggerRate"] == 1.0


def test_observe_answer_found_uses_result_types_not_answer_text() -> None:
    assert (
        observe_answer_found(
            [SimpleNamespace(resultType="KNOWLEDGE_ANSWERED", sources=[])]
        )
        is True
    )
    assert (
        observe_answer_found([SimpleNamespace(resultType="NO_KNOWLEDGE", sources=[])])
        is False
    )
    assert (
        observe_answer_found([SimpleNamespace(resultType="NEED_MORE_INFO", sources=[])])
        is None
    )
    # Greeting / empty issues must not count as found just because reply text exists.
    assert observe_answer_found([]) is False


def test_score_greeting_found_false_when_no_issues() -> None:
    case = AgentWorkflowEvalCase.from_dict(
        {
            "id": "workflow-v1-002",
            "message": "你好",
            "expectedRoute": "GREETING",
            "expectedIssueCount": 0,
            "expectedFound": False,
            "forbiddenActions": ["CREATE_TICKET", "HANDOFF"],
        }
    )
    score = score_agent_workflow_case(
        case=case,
        observed_route="GREETING",
        observed_issue_count=0,
        observed_issue_routes=(),
        observed_found=observe_answer_found([]),
        cited_titles=(),
        ticket_triggered=False,
        handoff_triggered=False,
        llm_calls=0,
        latency_ms=5.0,
    )
    assert score.supervisor_route_match == 1.0
    assert score.answer_found_match == 1.0
    assert score.handoff_false_trigger == 0.0


def test_observe_ticket_and_handoff_triggers() -> None:
    assert observe_ticket_triggered(
        [SimpleNamespace(resultType="TICKET_CREATED")],
        state=None,
    )
    assert not observe_ticket_triggered(
        [SimpleNamespace(resultType="NO_KNOWLEDGE")],
        state={"ticket_created": {"done": False}},
    )
    assert observe_ticket_triggered(
        [],
        state={"ticket_created": {"done": True}},
    )
    assert observe_handoff_triggered(
        state={"handoff_case": object(), "handoff_handled": True},
        answer="",
    )
    assert observe_handoff_triggered(
        state={"handoff_handled": True},
        answer="請回覆「建立派工單」或「聯絡線上客服」",
    )
    assert not observe_handoff_triggered(
        state={"handoff_handled": False},
        answer="你好！我是 IT 助手",
    )


def test_issue_routes_from_state_prefer_issue_objects() -> None:
    state = {
        "it_issues": [SimpleNamespace(route="KNOWLEDGE")],
        "issues": [SimpleNamespace(route="KNOWLEDGE")],
    }
    assert issue_routes_from_state(state=state, issue_results=[]) == ("KNOWLEDGE",)
    # IssueResult has no route; fall back only when state lacks issues.
    assert issue_routes_from_state(
        state={},
        issue_results=[SimpleNamespace(resultType="NO_KNOWLEDGE")],
    ) == ()


def test_no_knowledge_with_handoff_offer_scores_found_miss_and_handoff_false_trigger() -> (
    None
):
    case = AgentWorkflowEvalCase.from_dict(
        {
            "id": "workflow-v1-001",
            "message": "FortiClient 出現 -455 怎麼辦？",
            "expectedRoute": "KNOWLEDGE",
            "expectedIssueCount": 1,
            "expectedFound": True,
            "expectedDocuments": ["登入 FortiClient 出現錯訊"],
            "forbiddenActions": ["CREATE_TICKET", "HANDOFF"],
        }
    )
    issue_results = [SimpleNamespace(resultType="NO_KNOWLEDGE", sources=[])]
    state = {
        "handoff_handled": True,
        "handoff_case": object(),
        "it_issues": [SimpleNamespace(route="KNOWLEDGE")],
    }
    score = score_agent_workflow_case(
        case=case,
        observed_route="IT_SUPPORT",
        observed_issue_count=1,
        observed_issue_routes=issue_routes_from_state(
            state=state, issue_results=issue_results
        ),
        observed_found=observe_answer_found(issue_results),
        cited_titles=(),
        ticket_triggered=observe_ticket_triggered(issue_results, state=state),
        handoff_triggered=observe_handoff_triggered(state=state, answer="聯絡線上客服"),
        llm_calls=2,
        latency_ms=3000.0,
    )
    assert score.supervisor_route_match == 1.0
    assert score.issue_route_match == 1.0
    assert score.answer_found_match == 0.0
    assert score.ticket_false_trigger == 0.0
    assert score.handoff_false_trigger == 1.0
