"""Pure helpers for route distribution and per-issue route detail."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from operations_core.contracts import OperationalEvent
from operations_core.taxonomy import TaxonomyRepository

_ANSWER_EVENT_TYPES = frozenset({"answer.completed", "faq.answered", "knowledge.answered"})
_NO_ANSWER_RESULTS = frozenset({"NO_KNOWLEDGE", "FAILED"})
_SOURCE_EVENT_TYPES = frozenset({"faq.answered", "knowledge.retrieved", "knowledge.answered"})
_ATTRIBUTION_KEYS = (
    "faqIds",
    "faqKeys",
    "documentIds",
    "sourcePaths",
    "versionIds",
    "releaseIds",
)
_CITATION_FIELDS = (
    ("documentId", "documentIds"),
    ("sourcePath", "sourcePaths"),
    ("versionId", "versionIds"),
    ("releaseId", "releaseIds"),
)


def new_attribution() -> dict[str, Counter[str]]:
    return {key: Counter() for key in _ATTRIBUTION_KEYS}


def serialize_attribution(
    counters: dict[str, Counter[str]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        key_name: [{"id": value, "count": count} for value, count in counter.most_common()]
        for key_name, counter in counters.items()
    }


def matching_source_events(
    route_event: OperationalEvent,
    source_events: list[OperationalEvent],
) -> list[OperationalEvent]:
    return [
        source
        for source in source_events
        if (
            route_event.issue_occurrence_id
            and source.issue_occurrence_id == route_event.issue_occurrence_id
        )
        or (
            not route_event.issue_occurrence_id
            and source.correlation_id == route_event.correlation_id
            and source.turn_id == route_event.turn_id
            and source.issue_type_id == route_event.issue_type_id
        )
    ]


def observe_source_attribution(
    matching_sources: list[OperationalEvent],
) -> dict[str, set[str]]:
    observed: dict[str, set[str]] = defaultdict(set)
    for source in matching_sources:
        payload = source.payload
        if source.event_type == "faq.answered":
            if payload.get("faqId"):
                observed["faqIds"].add(str(payload["faqId"]))
            if payload.get("faqKey"):
                observed["faqKeys"].add(str(payload["faqKey"]))
        for field, key_name in _CITATION_FIELDS:
            if payload.get(field):
                observed[key_name].add(str(payload[field]))
        for citation in payload.get("citations") or []:
            if not isinstance(citation, dict):
                continue
            for field, key_name in _CITATION_FIELDS:
                if citation.get(field):
                    observed[key_name].add(str(citation[field]))
    return observed


def collect_route_attribution(
    route_events: list[OperationalEvent],
    source_events: list[OperationalEvent],
) -> tuple[
    dict[str, Counter[str]],
    dict[str, dict[str, Counter[str]]],
    dict[tuple[str, str], dict[str, Counter[str]]],
]:
    by_issue: dict[str, Counter[str]] = defaultdict(Counter)
    attribution_by_route: dict[str, dict[str, Counter[str]]] = defaultdict(new_attribution)
    attribution_by_issue_route: dict[tuple[str, str], dict[str, Counter[str]]] = defaultdict(
        new_attribution
    )

    for event in route_events:
        issue_key = event.issue_type_id or "other.unclassified"
        selected_route = str(event.payload.get("route") or "UNKNOWN")
        by_issue[issue_key][selected_route] += 1
        observed = observe_source_attribution(
            matching_source_events(event, source_events),
        )
        for key_name, values in observed.items():
            attribution_by_route[selected_route][key_name].update(values)
            attribution_by_issue_route[(issue_key, selected_route)][key_name].update(values)

    return by_issue, attribution_by_route, attribution_by_issue_route


def build_route_issue_items(
    by_issue: dict[str, Counter[str]],
    attribution_by_issue_route: dict[tuple[str, str], dict[str, Counter[str]]],
    taxonomy: TaxonomyRepository,
) -> list[dict[str, Any]]:
    issue_items: list[dict[str, Any]] = []
    for issue_id, routes in by_issue.items():
        record = taxonomy.get(issue_id)
        issue_items.append(
            {
                "issueTypeId": issue_id,
                "displayName": record.display_name if record else issue_id,
                "routes": [
                    {
                        "route": selected_route,
                        "count": count,
                        "attribution": serialize_attribution(
                            attribution_by_issue_route[(issue_id, selected_route)]
                        ),
                    }
                    for selected_route, count in routes.most_common()
                ],
            }
        )
    return issue_items


def filter_route_events(
    events: list[OperationalEvent],
    *,
    issue_type_id: str | None,
    route_filter: str | None,
) -> list[OperationalEvent]:
    return [
        event
        for event in events
        if event.event_type == "route.selected"
        and (issue_type_id is None or event.issue_type_id == issue_type_id)
        and (
            route_filter is None
            or str(event.payload.get("route") or "UNKNOWN").upper() == route_filter
        )
    ]


def source_events_for_routes(events: list[OperationalEvent]) -> list[OperationalEvent]:
    return [event for event in events if event.event_type in _SOURCE_EVENT_TYPES]


def index_turn_text(all_events: list[OperationalEvent]) -> tuple[dict[str, str], dict[str, str]]:
    turn_messages: dict[str, str] = {}
    turn_answers: dict[str, str] = {}
    for event in all_events:
        tid = event.turn_id or event.correlation_id or ""
        if not tid:
            continue
        payload = event.payload or {}
        if event.event_type == "turn.received":
            msg = payload.get("messageMasked") or payload.get("userMessage") or payload.get("text")
            if msg:
                if event.turn_id:
                    turn_messages[event.turn_id] = str(msg)
                if event.correlation_id:
                    turn_messages[event.correlation_id] = str(msg)
        elif event.event_type in _ANSWER_EVENT_TYPES:
            ans = payload.get("answerMasked") or payload.get("aiReply") or payload.get("text")
            if ans:
                if event.turn_id:
                    turn_answers[event.turn_id] = str(ans)
                if event.correlation_id:
                    turn_answers[event.correlation_id] = str(ans)
    return turn_messages, turn_answers


def issue_lookup_maps(
    all_events: list[OperationalEvent],
) -> tuple[dict[str, str], dict[str, str]]:
    correlation_to_issue: dict[str, str] = {}
    turn_to_issue: dict[str, str] = {}
    for event in all_events:
        if not event.issue_type_id:
            continue
        if event.correlation_id:
            correlation_to_issue[event.correlation_id] = event.issue_type_id
        if event.turn_id:
            turn_to_issue[event.turn_id] = event.issue_type_id
    return correlation_to_issue, turn_to_issue


def collect_issue_route_signals(
    all_events: list[OperationalEvent],
    *,
    issue_type_id: str,
    turn_messages: dict[str, str],
    turn_answers: dict[str, str],
    correlation_to_issue: dict[str, str],
    turn_to_issue: dict[str, str],
) -> tuple[list[dict[str, Any]], int, int, int]:
    negative_feedbacks: list[dict[str, Any]] = []
    handoff_count = 0
    no_answer_count = 0
    issue_event_count = 0

    for event in all_events:
        ev_issue = (
            event.issue_type_id
            or turn_to_issue.get(event.turn_id or "")
            or correlation_to_issue.get(event.correlation_id or "")
        )
        if ev_issue != issue_type_id:
            continue
        if event.event_type == "issue.extracted":
            issue_event_count += 1
        if event.event_type.startswith("handoff."):
            handoff_count += 1
        if (
            event.event_type in _ANSWER_EVENT_TYPES
            and event.payload.get("resultType") in _NO_ANSWER_RESULTS
        ):
            no_answer_count += 1
        if event.event_type == "feedback.recorded" and event.payload.get("rating") == "DOWN":
            payload = event.payload or {}
            negative_feedbacks.append(
                {
                    "eventId": event.event_id,
                    "occurredAt": event.occurred_at.isoformat(),
                    "conversationId": event.conversation_id,
                    "turnId": event.turn_id,
                    "reason": str(payload.get("reason") or "未填寫原因"),
                    "resolvedStatus": payload.get("resolvedStatus"),
                    "userMessage": (
                        turn_messages.get(event.turn_id or "")
                        or turn_messages.get(event.correlation_id or "")
                        or ""
                    ),
                    "aiReply": (
                        turn_answers.get(event.turn_id or "")
                        or turn_answers.get(event.correlation_id or "")
                        or ""
                    ),
                }
            )

    negative_feedbacks.sort(key=lambda item: item["occurredAt"], reverse=True)
    return negative_feedbacks, handoff_count, no_answer_count, issue_event_count
