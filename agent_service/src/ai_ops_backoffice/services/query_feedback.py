"""Domain query mixin: FeedbackQueryMixin."""

from __future__ import annotations

from typing import Any

from agent_service.operations.access import ActorContext
from collections import Counter
from agent_service.operations.contracts import OperationalEvent
from agent_service.operations.scope import filter_events_by_scope
from agent_service.operations.contracts import utc_now

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
    ) -> dict[str, Any]:
        events = filter_events_by_scope(await self._events(), actor, self.taxonomy)
        all_hits = [
            event
            for event in events
            if event.event_type == "faq.answered" and event.payload.get("faqKey") == faq_key
        ]
        now = utc_now()
        today_date = now.date().isoformat()
        current_iso = now.isocalendar()[:2]
        current_month = now.strftime("%Y-%m")

        today_hit_count = sum(
            1 for e in all_hits if e.occurred_at.date().isoformat() == today_date
        )
        this_week_hit_count = sum(
            1 for e in all_hits if e.occurred_at.isocalendar()[:2] == current_iso
        )
        this_month_hit_count = sum(
            1 for e in all_hits if e.occurred_at.strftime("%Y-%m") == current_month
        )
        total_hit_count = len(all_hits)

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

        by_day: Counter[str] = Counter()
        by_week: Counter[str] = Counter()
        by_month: Counter[str] = Counter()
        by_version: Counter[str] = Counter()
        for event in hits:
            occurred = event.occurred_at
            iso_year, iso_week, _ = occurred.isocalendar()
            by_day[occurred.date().isoformat()] += 1
            by_week[f"{iso_year}-W{iso_week:02d}"] += 1
            by_month[occurred.strftime("%Y-%m")] += 1
            by_version[str(event.payload.get("faqVersionId") or "legacy-unattributed")] += 1

        resolved_faq_id = faq_id or next(
            (str(e.payload.get("faqId")) for e in all_hits if e.payload.get("faqId")), None
        )
        return {
            "faqKey": faq_key,
            "faqId": resolved_faq_id,
            "totalHitCount": total_hit_count,
            "totalHits": total_hit_count,
            "todayHitCount": today_hit_count,
            "hitsToday": today_hit_count,
            "thisWeekHitCount": this_week_hit_count,
            "hitsThisWeek": this_week_hit_count,
            "thisMonthHitCount": this_month_hit_count,
            "hitsThisMonth": this_month_hit_count,
            "rangeHitCount": len(hits),
            "byDay": [{"period": key, "hitCount": value} for key, value in sorted(by_day.items())],
            "byWeek": [{"period": key, "hitCount": value} for key, value in sorted(by_week.items())],
            "byMonth": [
                {"period": key, "hitCount": value} for key, value in sorted(by_month.items())
            ],
            "byVersion": [
                {"versionId": key, "hitCount": value}
                for key, value in by_version.most_common()
            ],
            "recentHits": [
                {
                    "occurredAt": event.occurred_at.isoformat(),
                    "conversationId": event.conversation_id,
                    "turnId": event.turn_id,
                    "correlationId": event.correlation_id,
                    "faqId": event.payload.get("faqId") or resolved_faq_id,
                    "versionId": event.payload.get("faqVersionId"),
                }
                for event in sorted(hits, key=lambda item: item.occurred_at, reverse=True)[:50]
            ],
        }


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
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        all_events = await self._scoped_events(actor, period)
        conversation_cache: dict[str, list[OperationalEvent]] = {}
        for event in all_events:
            if not event.conversation_id:
                continue
            conversation_cache.setdefault(event.conversation_id, []).append(event)
        feedback_events = [
            event for event in all_events if event.event_type == "feedback.recorded"
        ]
        if rating:
            feedback_events = [
                event for event in feedback_events if event.payload.get("rating") == rating
            ]
        if reason:
            feedback_events = [
                event
                for event in feedback_events
                if str(event.payload.get("reason") or "").lower() == reason.lower()
            ]
        if resolved_status:
            feedback_events = [
                event
                for event in feedback_events
                if str(event.payload.get("resolvedStatus") or "").lower()
                == resolved_status.lower()
            ]
        feedback_events.sort(key=lambda item: item.occurred_at, reverse=True)
        filtered_items = []
        for event in feedback_events:
            trace = self._build_feedback_trace(event, conversation_cache=conversation_cache)
            if issue_type_id and trace.get("issueTypeId") != issue_type_id:
                continue
            if handoff is True and not trace.get("handoffOccurred"):
                continue
            if handoff is False and trace.get("handoffOccurred"):
                continue
            filtered_items.append(
                {
                    "occurredAt": event.occurred_at.isoformat(),
                    "conversationId": event.conversation_id,
                    "correlationId": event.correlation_id,
                    "rating": event.payload.get("rating"),
                    "reason": event.payload.get("reason"),
                    "resolvedStatus": event.payload.get("resolvedStatus"),
                    "issueId": event.payload.get("issueId"),
                    "trace": trace,
                }
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
            return {
                "issueTypeId": None,
                "issueDescriptionMasked": None,
                "classificationSource": None,
                "faqKey": None,
                "documentIds": [],
                "releaseIds": [],
                "handoffOccurred": False,
                "handoffStatus": None,
            }

        conv_events = conversation_cache.get(conversation_id, [])
        scoped = [
            event
            for event in conv_events
            if correlation_id is None or event.correlation_id == correlation_id
        ]
        if not scoped:
            scoped = conv_events

        issue_extracted = None
        issue_classified = None
        faq_key = None
        document_ids: list[str] = []
        release_ids: list[str] = []
        handoff_status = None
        handoff_occurred = False

        for event in scoped:
            if event.event_type == "issue.extracted":
                payload_issue_id = event.payload.get("issueId")
                if issue_id is None or payload_issue_id == issue_id:
                    issue_extracted = event
            if (
                event.event_type == "issue.classified"
                and issue_extracted
                and event.issue_occurrence_id == issue_extracted.issue_occurrence_id
            ):
                issue_classified = event
            if event.event_type == "faq.answered":
                faq_key = event.payload.get("faqKey") or faq_key
            if event.event_type in {"knowledge.retrieved", "knowledge.answered"}:
                document_id = event.payload.get("documentId")
                if document_id and document_id not in document_ids:
                    document_ids.append(str(document_id))
                release_id = event.payload.get("releaseId")
                if release_id and release_id not in release_ids:
                    release_ids.append(str(release_id))
                for citation in event.payload.get("citations") or []:
                    if not isinstance(citation, dict):
                        continue
                    citation_doc = citation.get("documentId")
                    if citation_doc and citation_doc not in document_ids:
                        document_ids.append(str(citation_doc))
            if event.event_type.startswith("handoff."):
                handoff_occurred = True
                handoff_status = event.payload.get("status") or event.event_type

        issue_type_id = None
        classification_source = None
        if issue_classified is not None:
            issue_type_id = issue_classified.issue_type_id
            classification_source = issue_classified.payload.get("classificationSource")
        elif issue_extracted is not None:
            issue_type_id = issue_extracted.issue_type_id

        record = self.taxonomy.get(issue_type_id) if issue_type_id else None
        return {
            "issueTypeId": issue_type_id,
            "issueTypeDisplayName": record.display_name if record else issue_type_id,
            "issueDescriptionMasked": (
                issue_extracted.payload.get("descriptionMasked") if issue_extracted else None
            ),
            "classificationSource": classification_source,
            "faqKey": faq_key,
            "documentIds": document_ids,
            "releaseIds": release_ids,
            "handoffOccurred": handoff_occurred,
            "handoffStatus": handoff_status,
        }

