"""Turn-event field extraction for conversation summaries."""

from __future__ import annotations

from typing import Any

from operations_core.contracts import OperationalEvent

_ANSWER_EVENT_TYPES = frozenset({"answer.completed", "faq.answered", "knowledge.answered"})
_KNOWLEDGE_EVENT_TYPES = frozenset({"knowledge.retrieved", "knowledge.answered"})


def related_turn_events(
    turn_event: OperationalEvent,
    events: list[OperationalEvent],
) -> list[OperationalEvent]:
    return [
        item
        for item in events
        if item.event_type != "turn.received"
        and item.correlation_id == turn_event.correlation_id
        and (not item.turn_id or item.turn_id == turn_event.turn_id)
    ]


def _first_payload_str(
    related: list[OperationalEvent],
    *,
    event_types: set[str] | frozenset[str] | None = None,
    key: str,
    extra_predicate: Any = None,
) -> str | None:
    for item in related:
        if event_types is not None and item.event_type not in event_types:
            continue
        if extra_predicate is not None and not extra_predicate(item):
            continue
        value = item.payload.get(key)
        if value:
            return str(value)
    return None


def extract_answer_fields(related: list[OperationalEvent]) -> dict[str, Any]:
    answer_masked = _first_payload_str(
        related,
        event_types=_ANSWER_EVENT_TYPES,
        key="answerMasked",
        extra_predicate=lambda item: item.payload.get("renderedResponse") is True,
    ) or _first_payload_str(related, event_types=_ANSWER_EVENT_TYPES, key="answerMasked")
    return {
        "issueTypeId": next((item.issue_type_id for item in related if item.issue_type_id), None),
        "route": _first_payload_str(related, event_types={"route.selected"}, key="route"),
        "model": _first_payload_str(related, event_types={"usage.recorded"}, key="model"),
        "resultType": _first_payload_str(
            related, event_types=_ANSWER_EVENT_TYPES, key="resultType"
        ),
        "answerMasked": answer_masked,
        "faqKey": _first_payload_str(related, event_types={"faq.answered"}, key="faqKey"),
        "handoffStatus": next(
            (
                str(item.payload.get("status") or item.event_type)
                for item in related
                if item.event_type.startswith("handoff.")
            ),
            None,
        ),
    }


def extract_knowledge_refs(related: list[OperationalEvent]) -> dict[str, list[str]]:
    document_ids: list[str] = []
    source_paths: list[str] = []
    release_ids: list[str] = []
    for item in related:
        if item.event_type not in _KNOWLEDGE_EVENT_TYPES:
            continue
        document_id = item.payload.get("documentId")
        if document_id and str(document_id) not in document_ids:
            document_ids.append(str(document_id))
        source_path = item.payload.get("sourcePath")
        if source_path and str(source_path) not in source_paths:
            source_paths.append(str(source_path))
        release_id = item.payload.get("releaseId")
        if release_id and str(release_id) not in release_ids:
            release_ids.append(str(release_id))
        for cit in item.payload.get("citations") or []:
            if not isinstance(cit, dict):
                continue
            sp = cit.get("sourcePath")
            if sp and str(sp) not in source_paths:
                source_paths.append(str(sp))
            did = cit.get("documentId")
            if did and str(did) not in document_ids:
                document_ids.append(str(did))
    return {
        "documentIds": document_ids,
        "sourcePaths": source_paths,
        "releaseIds": release_ids,
    }


def extract_feedback_fields(related: list[OperationalEvent]) -> dict[str, Any]:
    latest_feedback = max(
        (item for item in related if item.event_type == "feedback.recorded"),
        key=lambda item: item.occurred_at,
        default=None,
    )
    feedback_rating = (
        str(latest_feedback.payload["rating"])
        if latest_feedback and latest_feedback.payload.get("rating")
        else None
    )
    resolved_status = (
        str(latest_feedback.payload["resolvedStatus"])
        if latest_feedback and latest_feedback.payload.get("resolvedStatus")
        else None
    )
    return {"feedbackRating": feedback_rating, "resolvedStatus": resolved_status}


def extract_ticket_fields(related: list[OperationalEvent]) -> dict[str, Any]:
    ticket_created = next(
        (item for item in related if item.event_type == "ticket.created"),
        None,
    )
    ticket_failed = next(
        (item for item in related if item.event_type == "ticket.failed"),
        None,
    )
    ticket_event = ticket_created or ticket_failed
    ticket_id = (
        str(ticket_created.payload.get("ticketId"))
        if ticket_created and ticket_created.payload.get("ticketId")
        else next(
            (str(item.payload.get("ticketId")) for item in related if item.payload.get("ticketId")),
            None,
        )
    )
    if ticket_created:
        ticket_status: str | None = "CREATED"
    elif ticket_failed:
        ticket_status = "FAILED"
    elif ticket_event and ticket_event.payload.get("status"):
        ticket_status = str(ticket_event.payload.get("status"))
    else:
        ticket_status = None
    ticket_backend = (
        str(ticket_event.payload.get("backend"))
        if ticket_event and ticket_event.payload.get("backend")
        else None
    )
    return {
        "ticketId": ticket_id,
        "ticketStatus": ticket_status,
        "ticketBackend": ticket_backend,
    }


def summarize_turn_events(
    turn_event: OperationalEvent,
    events: list[OperationalEvent],
) -> dict[str, Any]:
    related = related_turn_events(turn_event, events)
    return {
        **extract_answer_fields(related),
        **extract_knowledge_refs(related),
        **extract_feedback_fields(related),
        **extract_ticket_fields(related),
    }
