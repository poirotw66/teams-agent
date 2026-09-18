"""Export job creation helpers for ExportsQueryMixin.create_export_job."""

from __future__ import annotations

from typing import Any


def build_export_create_filters(
    *,
    actor_ref: str | None,
    issue_type_id: str | None,
    route: str | None,
    conversation_id: str | None,
    model: str | None,
    has_feedback: bool | None,
    handoff: bool | None,
    rating: str | None,
    feedback_reason: str | None,
    resolved_status: str | None,
    channel_scope: str | None,
    query: str | None,
    source: str | None,
    status: str | None,
    owner_unit_id: str | None,
    format_type: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    snake_filters = {
        "actor_ref": actor_ref,
        "issue_type_id": issue_type_id,
        "route": route,
        "conversation_id": conversation_id,
        "model": model,
        "has_feedback": has_feedback,
        "handoff": handoff,
        "rating": rating,
        "feedback_reason": feedback_reason,
        "resolved_status": resolved_status,
        "channel_scope": channel_scope,
        "query": query,
        "source": source,
        "status": status,
        "owner_unit_id": owner_unit_id,
        "format_type": format_type,
    }
    camel_filters = {
        key: value
        for key, value in {
            "actorRef": actor_ref,
            "issueTypeId": issue_type_id,
            "route": route,
            "conversationId": conversation_id,
            "model": model,
            "hasFeedback": has_feedback,
            "handoff": handoff,
            "rating": rating,
            "reason": feedback_reason,
            "resolvedStatus": resolved_status,
            "channelScope": channel_scope,
            "query": query,
            "source": source,
            "status": status,
            "ownerUnitId": owner_unit_id,
            "formatType": format_type,
        }.items()
        if value is not None
    }
    return snake_filters, camel_filters
