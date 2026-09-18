"""Feedback list filtering helpers for FeedbackQueryMixin.list_feedback."""

from __future__ import annotations

from typing import Any

from operations_core.contracts import OperationalEvent


def filter_feedback_events(
    feedback_events: list[OperationalEvent],
    *,
    rating: str | None,
    reason: str | None,
    resolved_status: str | None,
) -> list[OperationalEvent]:
    filtered = list(feedback_events)
    if rating:
        filtered = [event for event in filtered if event.payload.get("rating") == rating]
    if reason:
        needle = reason.lower()
        filtered = [
            event
            for event in filtered
            if needle in str(event.payload.get("reason") or "").lower()
        ]
    if resolved_status:
        filtered = [
            event
            for event in filtered
            if str(event.payload.get("resolvedStatus") or "").lower()
            == resolved_status.lower()
        ]
    filtered.sort(key=lambda item: item.occurred_at, reverse=True)
    return filtered


def matching_issue_type_ids(taxonomy: Any, issue_type_id: str | None) -> set[str] | None:
    requested_issue = str(issue_type_id or "").strip()
    if not requested_issue:
        return None
    needle = requested_issue.casefold()
    matching = {
        record.issue_type_id
        for record in taxonomy.list_active()
        if needle in record.issue_type_id.casefold()
        or needle in record.display_name.casefold()
    }
    matching.add(requested_issue)
    return matching


def build_feedback_list_items(
    feedback_events: list[OperationalEvent],
    *,
    conversation_cache: dict[str, list[OperationalEvent]],
    matching_issue_ids: set[str] | None,
    route: str | None,
    model: str | None,
    handoff: bool | None,
    build_trace: Any,
) -> list[dict[str, Any]]:
    filtered_items: list[dict[str, Any]] = []
    for event in feedback_events:
        trace = build_trace(event, conversation_cache=conversation_cache)
        if matching_issue_ids is not None and trace.get("issueTypeId") not in matching_issue_ids:
            continue
        if route and trace.get("route") != route:
            continue
        if model and trace.get("model") != model:
            continue
        if handoff is True and not trace.get("handoffOccurred"):
            continue
        if handoff is False and trace.get("handoffOccurred"):
            continue
        filtered_items.append(
            {
                "occurredAt": event.occurred_at.isoformat(),
                "conversationId": event.conversation_id,
                "turnId": trace.get("turnId") or event.turn_id,
                "correlationId": event.correlation_id,
                "rating": event.payload.get("rating"),
                "reason": event.payload.get("reason"),
                "resolvedStatus": event.payload.get("resolvedStatus"),
                "issueId": event.payload.get("issueId"),
                "route": trace.get("route"),
                "model": trace.get("model"),
                "trace": trace,
            }
        )
    return filtered_items
