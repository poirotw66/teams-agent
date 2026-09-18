"""Answer-generation retry and rejection policies (pure).

I/O (LLM invoke, claim repair) remains on HybridKnowledgeService._generate.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_service.contracts import GroundedClaim
from agent_service.retrieval import SearchResult

from .grounding import (
    answer_covers_error_branches,
    answer_covers_procedure_steps,
    answer_covers_visual_evidence_plates,
    query_asks_for_procedure,
    query_asks_for_visual_evidence,
)
from .relevance import (
    answer_indicates_insufficient_information,
    query_lexically_matches_results,
)

_ERROR_BRANCH_QUERY_MARKERS: tuple[str, ...] = (
    "分流",
    "錯誤時",
    "各錯誤",
    "不同錯誤",
    "多個錯誤",
    "錯誤碼分流",
)


def query_asks_for_error_branching(query: str) -> bool:
    return any(marker in query for marker in _ERROR_BRANCH_QUERY_MARKERS)


def should_retry_false_none(
    *,
    answerability: str,
    results: Sequence[SearchResult],
    confidence_label: str,
    answer: str,
    claims: Sequence[GroundedClaim],
    resolved_issue_query: str,
) -> bool:
    """High-confidence retrieval produced NONE / empty claims despite lexical overlap."""
    return (
        answerability == "NONE"
        and bool(results)
        and confidence_label == "HIGH_CONFIDENCE_PASS"
        and (answer_indicates_insufficient_information(answer) or not claims)
        and query_lexically_matches_results(resolved_issue_query, list(results))
    )


def should_retry_error_coverage(
    *,
    answerability: str,
    resolved_issue_query: str,
    context_error_codes: Sequence[str],
    answer: str,
) -> bool:
    return (
        answerability in {"FULL", "PARTIAL"}
        and query_asks_for_error_branching(resolved_issue_query)
        and len(context_error_codes) >= 2
        and not answer_covers_error_branches(answer, list(context_error_codes))
    )


def should_retry_procedure_coverage(
    *,
    answerability: str,
    resolved_issue_query: str,
    context_procedure_steps: Sequence[str],
    answer: str,
) -> bool:
    return (
        answerability in {"FULL", "PARTIAL"}
        and query_asks_for_procedure(resolved_issue_query)
        and len(context_procedure_steps) >= 2
        and not answer_covers_procedure_steps(answer, list(context_procedure_steps))
    )


def should_retry_visual_evidence(
    *,
    answerability: str,
    resolved_issue_query: str,
    context_visual_plates: Sequence[str],
    answer: str,
) -> bool:
    return (
        answerability in {"FULL", "PARTIAL"}
        and query_asks_for_visual_evidence(resolved_issue_query)
        and len(context_visual_plates) >= 2
        and not answer_covers_visual_evidence_plates(answer, list(context_visual_plates))
    )


def should_keep_prior_after_visual_retry(
    *,
    context_procedure_steps: Sequence[str],
    answer: str,
) -> bool:
    """Reject a visual retry that drops previously covered procedure steps."""
    return bool(context_procedure_steps) and not answer_covers_procedure_steps(
        answer, list(context_procedure_steps)
    )


def is_unsupported_miss_answer(
    *,
    answer: str,
    answerability: str,
    claims: Sequence[GroundedClaim],
) -> bool:
    return answer_indicates_insufficient_information(answer) and (
        answerability == "NONE"
        or not claims
        or not any(
            not answer_indicates_insufficient_information(claim.text) for claim in claims
        )
    )


__all__ = [
    "is_unsupported_miss_answer",
    "query_asks_for_error_branching",
    "should_keep_prior_after_visual_retry",
    "should_retry_error_coverage",
    "should_retry_false_none",
    "should_retry_procedure_coverage",
    "should_retry_visual_evidence",
]
