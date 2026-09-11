from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query


def register_conversations_routes(
    app: FastAPI,
    *,
    query_service: Any,
    current_actor: Callable[..., Any],
    require_capability: Callable[[Any, str], None],
    audit_read: Callable[..., Any],
) -> None:
    """Register HTTP read routes for conversation list and detail."""

    @app.get("/api/conversations")
    async def conversations(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        cursor: str | None = None,
        actor_ref: str | None = None,
        user_id: str | None = None,
        issue_type_id: str | None = None,
        route: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
        has_feedback: bool | None = None,
        handoff: bool | None = None,
        channel_scope: str | None = None,
        query: str | None = None,
        source: str | None = None,
        refresh: bool = False,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.conversations.read")
        result = await query_service.list_conversations(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            cursor=cursor,
            actor_ref=actor_ref,
            user_id=user_id,
            issue_type_id=issue_type_id,
            route=route,
            conversation_id=conversation_id,
            model=model,
            has_feedback=has_feedback,
            handoff=handoff,
            channel_scope=channel_scope,
            query=query,
            source=source,
            force_refresh=refresh,
        )
        filter_details = {
            "days": days,
            "preset": preset,
            "startDate": start_date,
            "endDate": end_date,
            "cursor": cursor,
            "actorRef": actor_ref,
            "userId": user_id,
            "issueTypeId": issue_type_id,
            "route": route,
            "conversationId": conversation_id,
            "model": model,
            "hasFeedback": has_feedback,
            "handoff": handoff,
            "channelScope": channel_scope,
            "query": query,
            "source": source,
            "resultCount": len(result.get("items", [])),
        }
        await audit_read(
            actor,
            "query.conversations",
            "conversations",
            after={k: v for k, v in filter_details.items() if v is not None},
        )
        return result

    @app.get("/api/conversations/{conversation_id}")
    async def conversation_detail(
        conversation_id: str,
        unmask_reason: str | None = None,
        refresh: bool = False,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.conversations.read")
        if unmask_reason and not actor.has_capability("ops.conversations.unmasked"):
            raise HTTPException(
                status_code=403, detail="Unmasked conversation access is forbidden."
            )
        if unmask_reason and len(unmask_reason.strip()) < 3:
            raise HTTPException(
                status_code=400, detail="unmask_reason must be at least 3 characters."
            )
        detail = await query_service.conversation_detail(
            actor,
            conversation_id,
            unmask_reason=unmask_reason,
            force_refresh=refresh,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        action = (
            "query.conversation_unmasked"
            if detail.get("unmaskAuthorized")
            else "query.conversation_detail"
        )
        await audit_read(
            actor,
            action,
            conversation_id,
            after={"unmaskReason": unmask_reason} if unmask_reason else None,
        )
        return detail
