"""Tests for production-path AgentWorkflow evaluation contracts."""

from __future__ import annotations

import json
from pathlib import Path

from agent_service.agent_workflow_eval import (
    AgentWorkflowEvalCase,
    aggregate_agent_workflow_scores,
    score_agent_workflow_case,
)

EVAL_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "eval" / "agent_workflow_eval_v1.json"
)


def test_agent_workflow_eval_set_has_required_fields() -> None:
    payload = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    assert payload["caseCount"] == len(payload["cases"]) >= 3
    for raw in payload["cases"]:
        case = AgentWorkflowEvalCase.from_dict(raw)
        assert case.case_id
        assert case.message
        assert case.expected_route
        assert isinstance(case.forbidden_actions, tuple)


def test_score_agent_workflow_case_tracks_route_and_safety() -> None:
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
        observed_route="KNOWLEDGE",
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
    assert score.issue_count_match == 1.0
    assert score.answer_found_match == 1.0
    assert score.citation_precision == 0.5
    assert score.citation_recall == 1.0
    assert score.ticket_false_trigger == 1.0
    assert score.handoff_false_trigger == 0.0
    summary = aggregate_agent_workflow_scores([score])
    assert summary["caseCount"] == 1.0
    assert summary["ticketFalseTriggerRate"] == 1.0
