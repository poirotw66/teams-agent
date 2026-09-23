"""Tests for deterministic request LLM budget planning."""

from __future__ import annotations

from agent_service.llm_budget_plan import PlannedIssue, plan_request_llm_budget


def test_three_issues_with_six_slots_are_deterministic_across_runs() -> None:
    issues = (
        PlannedIssue(issue_id=1, query_tier="hard", allow_rewrite=True, allow_escalation=True),
        PlannedIssue(issue_id=2, query_tier="standard", allow_rewrite=True),
        PlannedIssue(issue_id=3, query_tier="trivial"),
    )
    plans = [
        plan_request_llm_budget(total_limit=6, already_used=0, issues=issues)
        for _ in range(100)
    ]
    first = plans[0]
    assert all(plan == first for plan in plans)
    assert [item.issue_id for item in first.issue_budgets] == [1, 2, 3]
    assert first.issue_budgets[0].answer_slots == 1
    assert first.issue_budgets[1].answer_slots == 1
    assert first.issue_budgets[2].answer_slots == 1


def test_hard_first_issue_cannot_consume_later_answer_slots() -> None:
    issues = (
        PlannedIssue(
            issue_id=1,
            query_tier="hard",
            allow_rewrite=True,
            allow_escalation=True,
        ),
        PlannedIssue(issue_id=2, query_tier="standard"),
        PlannedIssue(issue_id=3, query_tier="standard"),
    )
    plan = plan_request_llm_budget(total_limit=3, already_used=0, issues=issues)
    assert plan.unallocated_issue_ids == ()
    assert all(item.answer_slots == 1 for item in plan.issue_budgets)
    assert plan.issue_budgets[0].rewrite_slots == 0
    assert plan.issue_budgets[0].escalation_slots == 0


def test_unallocated_issues_when_answer_slots_exhausted() -> None:
    issues = tuple(
        PlannedIssue(issue_id=index, query_tier="standard") for index in range(1, 5)
    )
    plan = plan_request_llm_budget(total_limit=2, already_used=0, issues=issues)
    assert [item.issue_id for item in plan.issue_budgets] == [1, 2]
    assert plan.unallocated_issue_ids == (3, 4)
