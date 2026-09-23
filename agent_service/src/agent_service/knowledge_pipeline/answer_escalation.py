"""Hard-answer escalation decisions from trusted runtime signals only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EscalationReason = Literal[
    "HARD_TIER",
    "STRUCTURED_OUTPUT_FAILURE",
    "GROUNDING_FAILURE",
    "CLAIM_ALIGNMENT_FAILURE",
    "SAFETY_REPAIR_FAILURE",
    "HARD_MODEL_UNAVAILABLE",
]

_DIRECT_HARD = frozenset({"HARD_DIRECT", "HARD_OR_GROUNDING_FAILURE"})
_RETRY_HARD = frozenset({"ON_GROUNDING_FAILURE", "HARD_OR_GROUNDING_FAILURE"})
_ELIGIBLE_RETRY = frozenset(
    {
        "STRUCTURED_OUTPUT_FAILURE",
        "GROUNDING_FAILURE",
        "CLAIM_ALIGNMENT_FAILURE",
        "SAFETY_REPAIR_FAILURE",
    }
)


@dataclass(frozen=True)
class AnswerEscalationDecision:
    use_hard_model: bool
    reason: str | None
    escalated: bool
    attempt_count: int


def initial_answer_escalation(
    *,
    policy: str,
    query_tier: str | None,
    hard_model_available: bool,
) -> AnswerEscalationDecision:
    """Choose the first answer model. User text is never an escalation signal."""
    normalized = (policy or "OFF").strip().upper()
    if (
        normalized in _DIRECT_HARD
        and query_tier == "hard"
        and hard_model_available
    ):
        return AnswerEscalationDecision(
            use_hard_model=True,
            reason="HARD_TIER",
            escalated=True,
            attempt_count=1,
        )
    if normalized in _DIRECT_HARD and query_tier == "hard" and not hard_model_available:
        return AnswerEscalationDecision(
            use_hard_model=False,
            reason="HARD_MODEL_UNAVAILABLE",
            escalated=False,
            attempt_count=1,
        )
    return AnswerEscalationDecision(
        use_hard_model=False,
        reason=None,
        escalated=False,
        attempt_count=1,
    )


def retry_answer_escalation(
    *,
    policy: str,
    failure_reason: str | None,
    hard_model_available: bool,
    already_escalated: bool,
    has_evidence: bool,
    is_valid_no_answer: bool,
    deadline_allows_retry: bool = True,
    budget_allows_retry: bool = True,
    is_authorization_failure: bool = False,
) -> AnswerEscalationDecision:
    """Allow at most one hard-model retry after an eligible generation failure."""
    normalized = (policy or "OFF").strip().upper()
    if already_escalated or normalized not in _RETRY_HARD:
        return AnswerEscalationDecision(False, None, already_escalated, 1)
    blocked = (
        not has_evidence
        or is_valid_no_answer
        or is_authorization_failure
        or not deadline_allows_retry
        or not budget_allows_retry
        or failure_reason not in _ELIGIBLE_RETRY
    )
    if blocked:
        return AnswerEscalationDecision(False, None, already_escalated, 1)
    if not hard_model_available:
        return AnswerEscalationDecision(
            False, "HARD_MODEL_UNAVAILABLE", False, 1
        )
    return AnswerEscalationDecision(
        use_hard_model=True,
        reason=failure_reason,
        escalated=True,
        attempt_count=2,
    )


__all__ = [
    "AnswerEscalationDecision",
    "EscalationReason",
    "initial_answer_escalation",
    "retry_answer_escalation",
]
