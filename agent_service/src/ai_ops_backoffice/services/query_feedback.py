"""Domain query mixin: FeedbackQueryMixin."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from operations_core.access import ActorContext
from operations_core.contracts import OperationalEvent, utc_now
from operations_core.scope import filter_events_by_scope

from .periods import event_in_period
from .query_feedback_faq import aggregate_faq_hits
from .query_feedback_list import (
    build_feedback_list_items,
    filter_feedback_events,
    matching_issue_type_ids,
)
from .query_feedback_trace import collect_feedback_trace_signals, empty_feedback_trace

__all__ = ["FeedbackQueryMixin", "FeedbackQueryService", "utc_now"]


class FeedbackQueryMixin:
    async def faq_performance(
        self,
        actor: ActorContext,
        *,
        faq_key: str,
        faq_id: str | None = None,
        days: int | None = None,
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        events = filter_events_by_scope(await self._events(), actor, self.taxonomy)
        all_hits = [
            event
            for event in events
            if event.event_type == "faq.answered" and event.payload.get("faqKey") == faq_key
        ]
        if days or preset or start_date or end_date:
            period = self._resolve_period(
                preset=preset,
                days=days or 30,
                start_date=start_date,
                end_date=end_date,
            )
            hits = [e for e in all_hits if event_in_period(e.occurred_at, period)]
        else:
            hits = all_hits
        return aggregate_faq_hits(
            all_hits,
            hits,
            faq_key=faq_key,
            faq_id=faq_id,
            as_of=as_of or utc_now(),
        )

    async def list_feedback(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        rating: str | None = None,
        issue_type_id: str | None = None,
        reason: str | None = None,
        resolved_status: str | None = None,
        handoff: bool | None = None,
        model: str | None = None,
        route: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset, days=days, start_date=start_date, end_date=end_date
        )
        all_events = await self._scoped_events(actor, period)
        conversation_cache: dict[str, list[OperationalEvent]] = {}
        for event in all_events:
            if event.conversation_id:
                conversation_cache.setdefault(event.conversation_id, []).append(event)
        feedback_events = filter_feedback_events(
            [e for e in all_events if e.event_type == "feedback.recorded"],
            rating=rating,
            reason=reason,
            resolved_status=resolved_status,
        )
        filtered_items = build_feedback_list_items(
            feedback_events,
            conversation_cache=conversation_cache,
            matching_issue_ids=matching_issue_type_ids(self.taxonomy, issue_type_id),
            route=route,
            model=model,
            handoff=handoff,
            build_trace=self._build_feedback_trace,
        )
        start = max(0, int(cursor or "0"))
        items = filtered_items[start : start + limit]
        next_index = start + len(items)
        has_more = next_index < len(filtered_items)
        return {
            "items": items,
            "total": len(filtered_items),
            "nextCursor": str(next_index) if has_more else None,
            "hasMore": has_more,
        }

    def _build_feedback_trace(
        self,
        feedback_event: OperationalEvent,
        *,
        conversation_cache: dict[str, list[OperationalEvent]],
    ) -> dict[str, Any]:
        conversation_id = feedback_event.conversation_id
        correlation_id = feedback_event.correlation_id
        issue_id = feedback_event.payload.get("issueId")
        if not conversation_id:
            return empty_feedback_trace(feedback_event)

        conv_events = conversation_cache.get(conversation_id, [])
        scoped = [
            event
            for event in conv_events
            if correlation_id is None or event.correlation_id == correlation_id
        ]
        if not scoped:
            scoped = conv_events

        signals = collect_feedback_trace_signals(scoped, issue_id=issue_id)
        issue_extracted = signals["issue_extracted"]
        issue_classified = signals["issue_classified"]
        issue_type_id = None
        classification_source = None
        if issue_classified is not None:
            issue_type_id = issue_classified.issue_type_id
            classification_source = issue_classified.payload.get("classificationSource")
        elif issue_extracted is not None:
            issue_type_id = issue_extracted.issue_type_id

        record = self.taxonomy.get(issue_type_id) if issue_type_id else None
        source_trace = getattr(self, "source_trace", None)
        return {
            "turnId": feedback_event.turn_id,
            "issueTypeId": issue_type_id,
            "issueTypeDisplayName": record.display_name if record else issue_type_id,
            "issueDescriptionMasked": (
                issue_extracted.payload.get("descriptionMasked") if issue_extracted else None
            ),
            "classificationSource": classification_source,
            "faqKey": signals["faq_key"],
            "documentIds": signals["document_ids"],
            "releaseIds": signals["release_ids"],
            "sourceRefs": (
                source_trace.references_for_events(scoped)
                if source_trace is not None
                else []
            ),
            "handoffOccurred": signals["handoff_occurred"],
            "handoffStatus": signals["handoff_status"],
            "route": signals["detected_route"],
            "model": signals["detected_model"],
        }


FeedbackQueryService = FeedbackQueryMixin

