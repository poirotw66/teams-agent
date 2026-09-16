from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from agent_service.workflow_evaluation import (
    WorkflowEvaluationRecord,
    summarize_workflow_evaluation,
)

EVALUATION_SET = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "eval"
    / "workflow_routing_eval_set.json"
)
EXPECTED_CATEGORIES = {
    "greeting_with_it",
    "thanks_with_new_issue",
    "mixed_it_non_it",
    "short_followup",
    "unknown_best_effort",
    "multiple_issues",
    "topic_switch",
    "ticket_mention",
}
EXPECTED_METRICS = {
    "it_block_rate",
    "issue_split_accuracy",
    "unnecessary_clarification_rate",
    "retrieval_query_accuracy",
    "grounded_answer_rate",
    "llm_call_count",
    "latency_ms",
}


def _load_evaluation_set() -> dict:
    return json.loads(EVALUATION_SET.read_text(encoding="utf-8"))


def test_workflow_evaluation_set_has_balanced_coverage() -> None:
    evaluation_set = _load_evaluation_set()
    cases = evaluation_set["cases"]
    category_counts = Counter(case["category"] for case in cases)

    assert evaluation_set["caseCount"] == len(cases) == 56
    assert set(category_counts) == EXPECTED_CATEGORIES
    assert set(category_counts.values()) == {7}
    assert set(evaluation_set["metrics"]) == EXPECTED_METRICS


def test_workflow_evaluation_cases_define_safe_expected_outcomes() -> None:
    cases = _load_evaluation_set()["cases"]

    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        expected = case["expected"]
        assert case["turns"]
        assert expected["queries"]
        assert expected["issueCount"] == len(expected["queries"])
        assert expected["ticketCreated"] is False
        assert expected["supervisorMayTerminate"] is False


def test_workflow_evaluation_set_contains_no_direct_identifiers() -> None:
    serialized = EVALUATION_SET.read_text(encoding="utf-8")

    assert "@" not in serialized
    assert "entraObjectId" not in serialized
    assert "teamsUserId" not in serialized


def test_workflow_evaluation_summary_tracks_accuracy_cost_and_latency() -> None:
    records = [
        WorkflowEvaluationRecord(
            expected_queries=("VPN 斷線", "信箱收不到信"),
            observed_queries=("VPN 斷線", "信箱收不到信"),
            supervisor_terminated=False,
            observed_issue_count=2,
            clarification_count=0,
            max_expected_clarification_turns=0,
            expects_grounded_answer=True,
            has_grounded_answer=True,
            llm_call_count=3,
            latency_ms=120,
        ),
        WorkflowEvaluationRecord(
            expected_queries=("SAP 無法登入",),
            observed_queries=(),
            supervisor_terminated=True,
            observed_issue_count=0,
            clarification_count=1,
            max_expected_clarification_turns=0,
            expects_grounded_answer=True,
            has_grounded_answer=False,
            llm_call_count=1,
            latency_ms=40,
        ),
    ]

    summary = summarize_workflow_evaluation(records)

    assert summary.case_count == 2
    assert summary.it_block_rate == 0.5
    assert summary.issue_split_accuracy == 0.5
    assert summary.unnecessary_clarification_rate == 0.5
    assert summary.retrieval_query_accuracy == 0.5
    assert summary.grounded_answer_rate == 0.5
    assert summary.mean_llm_call_count == 2
    assert summary.p95_latency_ms == 120


def test_workflow_evaluation_summary_rejects_empty_run() -> None:
    with pytest.raises(ValueError, match="At least one"):
        summarize_workflow_evaluation([])
