"""Deterministic per-request LLM budget planning for multi-issue turns."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

QueryTier = Literal["trivial", "standard", "hard"]


@dataclass(frozen=True)
class IssueLlmBudget:
    issue_id: int
    answer_slots: int
    relevance_slots: int
    rewrite_slots: int
    escalation_slots: int

    @property
    def total_slots(self) -> int:
        return (
            self.answer_slots
            + self.relevance_slots
            + self.rewrite_slots
            + self.escalation_slots
        )


@dataclass(frozen=True)
class RequestLlmBudgetPlan:
    total_limit: int
    already_used: int
    issue_budgets: tuple[IssueLlmBudget, ...]
    unallocated_issue_ids: tuple[int, ...] = ()

    @property
    def remaining_capacity(self) -> int:
        planned = sum(item.total_slots for item in self.issue_budgets)
        return max(0, self.total_limit - self.already_used - planned)


@dataclass(frozen=True)
class PlannedIssue:
    issue_id: int
    query_tier: QueryTier = "standard"
    needs_answer: bool = True
    allow_relevance: bool = True
    allow_rewrite: bool = False
    allow_escalation: bool = False


def _allocate_one_slot(
    *,
    issues: Sequence[PlannedIssue],
    slots: dict[int, int],
    remaining: int,
    eligible: Callable[[PlannedIssue], bool],
    require_answer: bool,
    answer_slots: dict[int, int],
) -> int:
    for issue in issues:
        if require_answer and answer_slots[issue.issue_id] == 0:
            continue
        if not eligible(issue):
            continue
        if remaining <= 0:
            break
        slots[issue.issue_id] = 1
        remaining -= 1
    return remaining


def plan_request_llm_budget(
    *,
    total_limit: int,
    already_used: int,
    issues: Sequence[PlannedIssue],
) -> RequestLlmBudgetPlan:
    """Allocate LLM slots deterministically without racing concurrent issues."""
    if total_limit < 0 or already_used < 0:
        raise ValueError("total_limit and already_used must be >= 0")

    remaining = max(0, total_limit - already_used)
    answer_slots: dict[int, int] = {issue.issue_id: 0 for issue in issues}
    relevance_slots: dict[int, int] = {issue.issue_id: 0 for issue in issues}
    rewrite_slots: dict[int, int] = {issue.issue_id: 0 for issue in issues}
    escalation_slots: dict[int, int] = {issue.issue_id: 0 for issue in issues}
    unallocated: list[int] = []

    for issue in issues:
        if not issue.needs_answer:
            continue
        if remaining <= 0:
            unallocated.append(issue.issue_id)
            continue
        answer_slots[issue.issue_id] = 1
        remaining -= 1

    remaining = _allocate_one_slot(
        issues=issues,
        slots=relevance_slots,
        remaining=remaining,
        eligible=lambda issue: issue.allow_relevance and issue.query_tier != "trivial",
        require_answer=True,
        answer_slots=answer_slots,
    )
    remaining = _allocate_one_slot(
        issues=issues,
        slots=rewrite_slots,
        remaining=remaining,
        eligible=lambda issue: issue.allow_rewrite and issue.query_tier == "hard",
        require_answer=True,
        answer_slots=answer_slots,
    )
    _allocate_one_slot(
        issues=issues,
        slots=escalation_slots,
        remaining=remaining,
        eligible=lambda issue: issue.allow_escalation,
        require_answer=True,
        answer_slots=answer_slots,
    )
    budgets = tuple(
        IssueLlmBudget(
            issue_id=issue.issue_id,
            answer_slots=answer_slots[issue.issue_id],
            relevance_slots=relevance_slots[issue.issue_id],
            rewrite_slots=rewrite_slots[issue.issue_id],
            escalation_slots=escalation_slots[issue.issue_id],
        )
        for issue in issues
        if answer_slots[issue.issue_id]
        or relevance_slots[issue.issue_id]
        or rewrite_slots[issue.issue_id]
        or escalation_slots[issue.issue_id]
    )
    return RequestLlmBudgetPlan(
        total_limit=total_limit,
        already_used=already_used,
        issue_budgets=budgets,
        unallocated_issue_ids=tuple(unallocated),
    )


__all__ = [
    "IssueLlmBudget",
    "PlannedIssue",
    "RequestLlmBudgetPlan",
    "plan_request_llm_budget",
]
