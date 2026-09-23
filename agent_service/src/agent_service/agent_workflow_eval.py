"""Production-path AgentWorkflow evaluation contracts and scoring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# Eval-set labels (expectedRoute) vs production supervisor intents / issue routes.
_SUPERVISOR_TO_EVAL_ROUTE: dict[str, str] = {
    "IT_SUPPORT": "KNOWLEDGE",
    "GREETING": "GREETING",
    "NON_IT": "NOT_IT",
    "TICKET_CREATE": "TICKET",
    "TICKET_QUERY": "TICKET",
    "HUMAN_ESCALATION": "HANDOFF",
    "ASSISTANT_META": "META",
    "UNKNOWN": "UNKNOWN",
    "FAQ": "FAQ",
    "KNOWLEDGE": "KNOWLEDGE",
    "TICKET": "TICKET",
    "NOT_IT": "NOT_IT",
    "HANDOFF": "HANDOFF",
    "META": "META",
}

_KNOWLEDGE_FOUND_TYPES = frozenset({"KNOWLEDGE_ANSWERED", "FAQ_ANSWERED"})
_KNOWLEDGE_MISS_TYPES = frozenset({"NO_KNOWLEDGE", "FAILED"})


def normalize_eval_route(route: str | None) -> str | None:
    """Map supervisor intents and issue routes onto eval ``expectedRoute`` labels."""
    if route is None:
        return None
    normalized = str(route).strip().upper()
    if not normalized:
        return None
    return _SUPERVISOR_TO_EVAL_ROUTE.get(normalized, normalized)


def routes_equivalent(expected: str | None, observed: str | None) -> bool:
    """True when observed production route matches an eval expectedRoute label."""
    left = normalize_eval_route(expected)
    right = normalize_eval_route(observed)
    if left is None or right is None:
        return False
    if left == right:
        return True
    # FAQ answers still satisfy a knowledge-path expectation.
    return {left, right} <= {"KNOWLEDGE", "FAQ"}


def observe_answer_found(issue_results: Sequence[Any]) -> bool | None:
    """Derive knowledge found/miss from IssueResult types (never from answer text).

    Returns:
      True for FAQ/KNOWLEDGE answered, False for NO_KNOWLEDGE/FAILED or no issues,
      None when the turn is still clarifying (NEED_MORE_INFO) so found is unlabeled.
    """
    result_types: list[str] = []
    for item in issue_results:
        result_type = getattr(item, "resultType", None)
        if result_type is None and isinstance(item, dict):
            result_type = item.get("resultType")
        if result_type:
            result_types.append(str(result_type).upper())
    if any(item in _KNOWLEDGE_FOUND_TYPES for item in result_types):
        return True
    if any(item in _KNOWLEDGE_MISS_TYPES for item in result_types):
        return False
    if any(item == "NEED_MORE_INFO" for item in result_types):
        return None
    # Greeting / non-IT / empty issue list: not a knowledge hit.
    return False


def observe_ticket_triggered(
    issue_results: Sequence[Any],
    *,
    state: Any | None = None,
) -> bool:
    """True only when a ticket was actually created (not merely offered)."""
    for item in issue_results:
        result_type = getattr(item, "resultType", None)
        if result_type is None and isinstance(item, dict):
            result_type = item.get("resultType")
        if str(result_type or "").upper() == "TICKET_CREATED":
            return True
    if not isinstance(state, dict):
        return False
    ticket_created = state.get("ticket_created")
    if isinstance(ticket_created, dict):
        return bool(ticket_created.get("done"))
    return bool(ticket_created)


def observe_handoff_triggered(*, state: Any | None, answer: str = "") -> bool:
    """True when a handoff case/offer was opened (not a no-op handoff route pass)."""
    text = str(answer or "")
    offer_copy = "聯絡線上客服" in text and (
        "建立派工單" in text or "案件摘要" in text
    )
    if isinstance(state, dict):
        if state.get("handoff_case") is not None:
            return True
        if state.get("handoff_handled") and offer_copy:
            return True
    return offer_copy


def issue_routes_from_state(
    *,
    state: Any | None,
    issue_results: Sequence[Any] = (),
) -> tuple[str, ...]:
    """Prefer Issue.route from workflow state; IssueResult has no route field."""
    routes: list[str] = []
    if isinstance(state, dict):
        for collection_key in ("it_issues", "issues"):
            for issue in state.get(collection_key) or []:
                route = getattr(issue, "route", None)
                if route is None and isinstance(issue, dict):
                    route = issue.get("route")
                if route:
                    routes.append(str(route).upper())
            if routes:
                return tuple(dict.fromkeys(routes))
    for item in issue_results:
        route = getattr(item, "route", None)
        if route is None and isinstance(item, dict):
            route = item.get("route")
        if route:
            routes.append(str(route).upper())
    return tuple(dict.fromkeys(routes))


@dataclass(frozen=True)
class AgentWorkflowEvalCase:
    case_id: str
    message: str
    prior_turns: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    expected_route: str | None = None
    expected_issue_count: int | None = None
    expected_found: bool | None = None
    expected_documents: tuple[str, ...] = ()
    expected_evidence: tuple[tuple[str, ...], ...] = ()
    forbidden_actions: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AgentWorkflowEvalCase:
        evidence_raw = value.get("expectedEvidence") or ()
        evidence: list[tuple[str, ...]] = []
        for item in evidence_raw:
            if isinstance(item, dict):
                must = item.get("mustContain") or item.get("must_contain") or ()
                evidence.append(tuple(str(token) for token in must if token))
            elif isinstance(item, (list, tuple)):
                evidence.append(tuple(str(token) for token in item if token))
        prior = value.get("priorTurns") or value.get("prior_turns") or ()
        return cls(
            case_id=str(value.get("id") or value.get("caseId") or ""),
            message=str(value.get("message") or value.get("query") or ""),
            prior_turns=tuple(str(item) for item in prior if str(item).strip()),
            groups=tuple(
                str(item).strip()
                for item in (value.get("groups") or ())
                if str(item).strip()
            ),
            expected_route=(
                str(value["expectedRoute"]).strip().upper()
                if value.get("expectedRoute")
                else None
            ),
            expected_issue_count=(
                int(value["expectedIssueCount"])
                if value.get("expectedIssueCount") is not None
                else None
            ),
            expected_found=(
                bool(value["expectedFound"])
                if value.get("expectedFound") is not None
                else None
            ),
            expected_documents=tuple(
                str(item)
                for item in (
                    value.get("expectedDocuments")
                    or value.get("expectedSourceTitles")
                    or ()
                )
            ),
            expected_evidence=tuple(evidence),
            forbidden_actions=tuple(
                str(item).strip().upper()
                for item in (value.get("forbiddenActions") or ())
                if str(item).strip()
            ),
        )


@dataclass(frozen=True)
class AgentWorkflowCaseScore:
    case_id: str
    supervisor_route_match: float | None
    issue_count_match: float | None
    issue_route_match: float | None
    answer_found_match: float | None
    citation_precision: float | None
    citation_recall: float | None
    ticket_false_trigger: float
    handoff_false_trigger: float
    llm_calls: int
    latency_ms: float
    first_stage_latency_ms: float | None = None


def score_agent_workflow_case(
    *,
    case: AgentWorkflowEvalCase,
    observed_route: str | None,
    observed_issue_count: int | None,
    observed_issue_routes: tuple[str, ...] = (),
    observed_found: bool | None = None,
    cited_titles: tuple[str, ...] = (),
    ticket_triggered: bool = False,
    handoff_triggered: bool = False,
    llm_calls: int = 0,
    latency_ms: float = 0.0,
    first_stage_latency_ms: float | None = None,
) -> AgentWorkflowCaseScore:
    route_match = None
    if case.expected_route is not None and observed_route is not None:
        route_match = (
            1.0 if routes_equivalent(case.expected_route, observed_route) else 0.0
        )

    issue_count_match = None
    if case.expected_issue_count is not None and observed_issue_count is not None:
        issue_count_match = (
            1.0 if int(observed_issue_count) == int(case.expected_issue_count) else 0.0
        )

    issue_route_match = None
    if case.expected_route is not None and observed_issue_routes:
        issue_route_match = (
            1.0
            if any(
                routes_equivalent(case.expected_route, route)
                for route in observed_issue_routes
            )
            else 0.0
        )

    found_match = None
    if case.expected_found is not None and observed_found is not None:
        found_match = 1.0 if bool(observed_found) == bool(case.expected_found) else 0.0

    citation_precision = None
    citation_recall = None
    expected_docs = set(case.expected_documents)
    cited = [title for title in cited_titles if title]
    if expected_docs and cited:
        hits = sum(1 for title in cited if title in expected_docs)
        citation_precision = hits / len(cited)
        citation_recall = sum(1 for title in expected_docs if title in cited) / len(
            expected_docs
        )
    elif expected_docs and not cited:
        citation_precision = 0.0
        citation_recall = 0.0

    ticket_false = (
        1.0
        if ticket_triggered and "CREATE_TICKET" in case.forbidden_actions
        else 0.0
    )
    handoff_false = (
        1.0 if handoff_triggered and "HANDOFF" in case.forbidden_actions else 0.0
    )
    return AgentWorkflowCaseScore(
        case_id=case.case_id,
        supervisor_route_match=route_match,
        issue_count_match=issue_count_match,
        issue_route_match=issue_route_match,
        answer_found_match=found_match,
        citation_precision=citation_precision,
        citation_recall=citation_recall,
        ticket_false_trigger=ticket_false,
        handoff_false_trigger=handoff_false,
        llm_calls=int(llm_calls),
        latency_ms=float(latency_ms),
        first_stage_latency_ms=first_stage_latency_ms,
    )


def aggregate_agent_workflow_scores(
    scores: list[AgentWorkflowCaseScore],
) -> dict[str, float]:
    if not scores:
        return {
            "caseCount": 0.0,
            "supervisorRouteAccuracy": 0.0,
            "issueCountAccuracy": 0.0,
            "issueRouteAccuracy": 0.0,
            "answerAccuracy": 0.0,
            "citationPrecision": 0.0,
            "citationRecall": 0.0,
            "ticketFalseTriggerRate": 0.0,
            "handoffFalseTriggerRate": 0.0,
            "llmCallsPerRequest": 0.0,
            "latencyMsP50": 0.0,
            "latencyMsP95": 0.0,
            "firstStageLatencyMsP50": 0.0,
            "firstStageLatencyMsP95": 0.0,
        }

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def _labeled(attr: str) -> list[float]:
        return [
            float(getattr(score, attr))
            for score in scores
            if getattr(score, attr) is not None
        ]

    latencies = sorted(score.latency_ms for score in scores)
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    first_stages = sorted(
        float(score.first_stage_latency_ms)
        for score in scores
        if score.first_stage_latency_ms is not None
    )
    first_p50 = first_stages[len(first_stages) // 2] if first_stages else 0.0
    first_p95 = (
        first_stages[max(0, int(len(first_stages) * 0.95) - 1)] if first_stages else 0.0
    )
    return {
        "caseCount": float(len(scores)),
        "supervisorRouteAccuracy": _mean(_labeled("supervisor_route_match")),
        "issueCountAccuracy": _mean(_labeled("issue_count_match")),
        "issueRouteAccuracy": _mean(_labeled("issue_route_match")),
        "answerAccuracy": _mean(_labeled("answer_found_match")),
        "citationPrecision": _mean(_labeled("citation_precision")),
        "citationRecall": _mean(_labeled("citation_recall")),
        "ticketFalseTriggerRate": _mean(
            [score.ticket_false_trigger for score in scores]
        ),
        "handoffFalseTriggerRate": _mean(
            [score.handoff_false_trigger for score in scores]
        ),
        "llmCallsPerRequest": _mean([float(score.llm_calls) for score in scores]),
        "latencyMsP50": float(p50),
        "latencyMsP95": float(p95),
        "firstStageLatencyMsP50": float(first_p50),
        "firstStageLatencyMsP95": float(first_p95),
    }


__all__ = [
    "AgentWorkflowCaseScore",
    "AgentWorkflowEvalCase",
    "aggregate_agent_workflow_scores",
    "issue_routes_from_state",
    "normalize_eval_route",
    "observe_answer_found",
    "observe_handoff_triggered",
    "observe_ticket_triggered",
    "routes_equivalent",
    "score_agent_workflow_case",
]
