"""Export job data-fetch helpers for ExportsQueryMixin.execute."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext


async def fetch_export_data(
    service: Any,
    *,
    actor: ActorContext,
    export_type: str,
    period_kwargs: dict[str, Any],
    filters: dict[str, Any],
    job_days: int,
    export_max_records: int,
) -> dict[str, Any]:
    if export_type == "operations_summary":
        return await service.operations_summary(actor, **period_kwargs)
    if export_type == "issues_summary":
        return await service.issues_summary(
            actor,
            **period_kwargs,
            query=filters.get("query"),
        )
    if export_type == "costs_summary":
        return await service.costs_summary(
            actor,
            **period_kwargs,
            model=filters.get("model"),
        )
    if export_type == "feedback":
        return await service.list_feedback(
            actor,
            **period_kwargs,
            rating=filters.get("rating"),
            issue_type_id=filters.get("issue_type_id"),
            reason=filters.get("feedback_reason"),
            resolved_status=filters.get("resolved_status"),
            handoff=filters.get("handoff"),
            model=filters.get("model"),
            route=filters.get("route"),
            limit=export_max_records + 1,
        )
    if export_type == "routes_summary":
        return await service.routes_summary(
            actor,
            **period_kwargs,
            issue_type_id=filters.get("issue_type_id"),
            route=filters.get("route"),
        )
    if export_type == "knowledge_performance":
        return await service.list_documents(
            actor,
            status=filters.get("status"),
            owner_unit_id=filters.get("owner_unit_id"),
            query=filters.get("query"),
            format_type=filters.get("format_type"),
            preset=period_kwargs.get("preset"),
            days=period_kwargs.get("days") or job_days,
            limit=export_max_records + 1,
        )
    if export_type == "conversations":
        return await service.list_conversations(
            actor,
            **period_kwargs,
            limit=export_max_records + 1,
            actor_ref=filters.get("actor_ref"),
            user_id=filters.get("user_id"),
            issue_type_id=filters.get("issue_type_id"),
            route=filters.get("route"),
            conversation_id=filters.get("conversation_id"),
            model=filters.get("model"),
            has_feedback=filters.get("has_feedback"),
            handoff=filters.get("handoff"),
            channel_scope=filters.get("channel_scope"),
            query=filters.get("query"),
            source=filters.get("source"),
        )
    raise ValueError(f"Unsupported export type: {export_type}")


def export_query_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "actorRef": filters.get("actor_ref"),
            "userId": filters.get("user_id"),
            "issueTypeId": filters.get("issue_type_id"),
            "route": filters.get("route"),
            "conversationId": filters.get("conversation_id"),
            "model": filters.get("model"),
            "hasFeedback": filters.get("has_feedback"),
            "handoff": filters.get("handoff"),
            "rating": filters.get("rating"),
            "reason": filters.get("feedback_reason"),
            "resolvedStatus": filters.get("resolved_status"),
            "channelScope": filters.get("channel_scope"),
            "query": filters.get("query"),
            "source": filters.get("source"),
            "status": filters.get("status"),
            "ownerUnitId": filters.get("owner_unit_id"),
            "formatType": filters.get("format_type"),
        }.items()
        if value is not None
    }
