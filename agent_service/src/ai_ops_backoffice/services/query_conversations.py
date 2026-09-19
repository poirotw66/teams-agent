"""Conversation list/detail queries for the AI Ops backoffice."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext
from operations_core.scope import filter_events_by_scope

from .query_conversations_detail_ops import build_conversation_detail_payload
from .query_conversations_filters import _matched_turn_for_filters
from .query_conversations_list_ops import (
    attach_conversation_freshness,
    build_conversation_list_item,
    group_events_by_conversation,
    select_conversation_page,
)

__all__ = [
    "ConversationQueryService",
    "ConversationsQueryMixin",
    "_matched_turn_for_filters",
]


class ConversationsQueryMixin:
    """Domain query helpers mixed into BackofficeQueryService."""

    async def list_conversations(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 25,
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
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        effective_days = (
            365
            if conversation_id and days == 30 and start_date is None and preset is None
            else days
        )
        period = self._resolve_period(
            preset=preset,
            days=effective_days,
            start_date=start_date,
            end_date=end_date,
        )
        events = await self._scoped_events(actor, period, force_refresh=force_refresh)
        grouped = group_events_by_conversation(events)
        user_filter = actor_ref or user_id
        filtered_ids, page_ids, start = select_conversation_page(
            grouped,
            conversation_id=conversation_id,
            channel_scope=channel_scope,
            user_filter=user_filter,
            query=query,
            source=source,
            issue_type_id=issue_type_id,
            route=route,
            model=model,
            has_feedback=has_feedback,
            handoff=handoff,
            cursor=cursor,
            limit=limit,
        )
        items = [
            build_conversation_list_item(
                conv_id,
                grouped[conv_id],
                source_trace=getattr(self, "source_trace", None),
                query=query,
                source=source,
                issue_type_id=issue_type_id,
                route=route,
                model=model,
                has_feedback=has_feedback,
                handoff=handoff,
                user_filter=user_filter,
            )
            for conv_id in page_ids
        ]
        next_index = start + len(page_ids)
        return {
            "items": items,
            "nextCursor": str(next_index) if next_index < len(filtered_ids) else None,
            "hasMore": next_index < len(filtered_ids),
            "freshness": attach_conversation_freshness(
                tracker=getattr(self, "_freshness_tracker", None),
                actor=actor,
                items=items,
            ),
        }

    async def conversation_detail(
        self,
        actor: ActorContext,
        conversation_id: str,
        *,
        unmask_reason: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        events = filter_events_by_scope(
            [
                event
                for event in await self._events(force_refresh=force_refresh)
                if event.conversation_id == conversation_id
            ],
            actor,
            self.taxonomy,
        )
        if not events:
            return None
        return build_conversation_detail_payload(
            conversation_id=conversation_id,
            events=events,
            actor=actor,
            taxonomy=self.taxonomy,
            source_trace=getattr(self, "source_trace", None),
            unmask_reason=unmask_reason,
        )


ConversationQueryService = ConversationsQueryMixin

