"""Conversation filter matching for list and turn selection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from operations_core.contracts import OperationalEvent

TurnPredicate = Callable[[dict[str, Any], dict[str, Any]], bool]


def _query_turn_predicate(needle: str) -> TurnPredicate:
    def query_matches(turn: dict[str, Any], payload: dict[str, Any]) -> bool:
        values = [
            turn.get("userMessage"),
            turn.get("aiReply"),
            turn.get("ticketId"),
            *(
                payload.get(field)
                for field in (
                    "messageMasked",
                    "answerMasked",
                    "descriptionMasked",
                    "userMessage",
                    "aiReply",
                    "text",
                    "ticketId",
                )
            ),
        ]
        return any(value and needle in str(value).casefold() for value in values)

    return query_matches


def _source_turn_predicate(needle: str) -> TurnPredicate:
    def source_matches(turn: dict[str, Any], payload: dict[str, Any]) -> bool:
        values = [
            *(turn.get("documentIds") or []),
            *(turn.get("sourcePaths") or []),
            *(turn.get("releaseIds") or []),
            payload.get("documentId"),
            payload.get("sourcePath"),
            payload.get("faqKey"),
            payload.get("releaseId"),
        ]
        refs = turn.get("sourceRefs") or []
        values.extend(
            ref.get(key)
            for ref in refs
            if isinstance(ref, dict)
            for key in ("documentId", "sourcePath", "title", "chunkId")
        )
        citations = payload.get("citations") or []
        values.extend(
            citation.get(key)
            for citation in citations
            if isinstance(citation, dict)
            for key in ("documentId", "sourcePath", "title", "chunkId")
        )
        return any(value and needle in str(value).casefold() for value in values)

    return source_matches


def _build_turn_filters(
    *,
    query: str | None,
    source: str | None,
    issue_type_id: str | None,
    route: str | None,
    model: str | None,
    has_feedback: bool | None,
    handoff: bool | None,
    user_filter: str | None,
) -> list[tuple[str, TurnPredicate]]:
    active_filters: list[tuple[str, TurnPredicate]] = []
    if query:
        active_filters.append(("query", _query_turn_predicate(query.casefold())))
    if source:
        active_filters.append(("source", _source_turn_predicate(source.casefold())))
    if issue_type_id:
        active_filters.append(
            ("issue_type", lambda turn, _payload: turn.get("issueTypeId") == issue_type_id)
        )
    if route:
        active_filters.append(("route", lambda turn, _payload: turn.get("route") == route))
    if model:
        active_filters.append(("model", lambda turn, _payload: turn.get("model") == model))
    if has_feedback is not None:
        active_filters.append(
            ("feedback", lambda turn, _payload: bool(turn.get("feedbackRating")) is has_feedback),
        )
    if handoff is not None:
        active_filters.append(
            ("handoff", lambda turn, _payload: bool(turn.get("handoffStatus")) is handoff),
        )
    if user_filter:
        active_filters.append(
            ("user", lambda turn, _payload: turn.get("actorRef") == user_filter),
        )
    return active_filters


def matched_turn_for_filters(
    turn_records: list[dict[str, Any]],
    turn_payloads: dict[str, dict[str, Any]],
    *,
    query: str | None,
    source: str | None,
    issue_type_id: str | None,
    route: str | None,
    model: str | None,
    has_feedback: bool | None,
    handoff: bool | None,
    user_filter: str | None,
) -> tuple[str | None, list[str]]:
    """Pick the turn that actually matched a conversation filter."""
    active_filters = _build_turn_filters(
        query=query,
        source=source,
        issue_type_id=issue_type_id,
        route=route,
        model=model,
        has_feedback=has_feedback,
        handoff=handoff,
        user_filter=user_filter,
    )
    if not turn_records:
        return None, []
    if not active_filters:
        turn = turn_records[-1]
        return turn.get("turnId"), ["latest"]

    scored: list[tuple[int, int, dict[str, Any], list[str]]] = []
    for index, turn in enumerate(turn_records):
        payload = turn_payloads.get(str(turn.get("turnId")), {})
        reasons = [name for name, predicate in active_filters if predicate(turn, payload)]
        scored.append((len(reasons), index, turn, reasons))

    # Prefer a turn satisfying all filters; otherwise choose the most relevant
    # available turn and expose the reasons that matched it.
    _score, _index, selected, reasons = max(scored, key=lambda item: (item[0], item[1]))
    return selected.get("turnId"), reasons


def _events_match_query(conv_events: list[OperationalEvent], query: str) -> bool:
    needle = query.casefold()
    for event in conv_events:
        payload = event.payload or {}
        for field in (
            "messageMasked",
            "answerMasked",
            "descriptionMasked",
            "userMessage",
            "aiReply",
            "text",
            "ticketId",
        ):
            val = payload.get(field)
            if val and needle in str(val).casefold():
                return True
    return False


def _events_match_source(conv_events: list[OperationalEvent], source: str) -> bool:
    needle = source.casefold()
    for event in conv_events:
        payload = event.payload or {}
        for field in ("documentId", "sourcePath", "faqKey", "releaseId"):
            val = payload.get(field)
            if val and needle in str(val).casefold():
                return True
        for cit in payload.get("citations") or []:
            if isinstance(cit, dict) and any(
                needle in str(cit.get(key) or "").casefold()
                for key in ("documentId", "sourcePath", "title", "chunkId")
            ):
                return True
    return False


def conversation_matches_filters(
    conv_events: list[OperationalEvent],
    *,
    conversation_id: str | None,
    cid: str,
    channel_scope: str | None,
    user_filter: str | None,
    query: str | None,
    source: str | None,
    issue_type_id: str | None,
    route: str | None,
    model: str | None,
    has_feedback: bool | None,
    handoff: bool | None,
) -> bool:
    if conversation_id and cid != conversation_id:
        return False
    if channel_scope and not any(event.channel_scope == channel_scope for event in conv_events):
        return False
    if user_filter and not any(
        event.actor_ref == user_filter
        or str(event.payload.get("userId") or "") == user_filter
        or str(event.payload.get("user") or "") == user_filter
        for event in conv_events
    ):
        return False
    if query and not _events_match_query(conv_events, query):
        return False
    if source and not _events_match_source(conv_events, source):
        return False
    if issue_type_id and not any(event.issue_type_id == issue_type_id for event in conv_events):
        return False
    if route and not any(
        event.event_type == "route.selected" and str(event.payload.get("route")) == route
        for event in conv_events
    ):
        return False
    if model and not any(
        event.event_type == "usage.recorded" and str(event.payload.get("model") or "") == model
        for event in conv_events
    ):
        return False
    has_feedback_event = any(event.event_type == "feedback.recorded" for event in conv_events)
    if has_feedback is True and not has_feedback_event:
        return False
    if has_feedback is False and has_feedback_event:
        return False
    has_handoff_event = any(event.event_type.startswith("handoff.") for event in conv_events)
    if handoff is True and not has_handoff_event:
        return False
    return not (handoff is False and has_handoff_event)


# Backward-compatible private alias.
_matched_turn_for_filters = matched_turn_for_filters
