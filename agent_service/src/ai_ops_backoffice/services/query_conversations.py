"""Conversation list/detail queries for the AI Ops backoffice."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.scope import filter_events_by_scope

from .query_helpers import _summarize_turn_events
from .query_math import percentile as _percentile


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
        grouped: dict[str, list[OperationalEvent]] = defaultdict(list)
        for event in events:
            if event.conversation_id:
                grouped[event.conversation_id].append(event)
        conversation_ids = sorted(
            grouped,
            key=lambda cid: max(item.occurred_at for item in grouped[cid]),
            reverse=True,
        )
        user_filter = actor_ref or user_id
        filtered_ids: list[str] = []
        for cid in conversation_ids:
            if conversation_id and cid != conversation_id:
                continue
            conv_events = grouped[cid]
            if channel_scope and not any(
                event.channel_scope == channel_scope for event in conv_events
            ):
                continue
            if user_filter and not any(
                event.actor_ref == user_filter
                or str(event.payload.get("userId") or "") == user_filter
                or str(event.payload.get("user") or "") == user_filter
                for event in conv_events
            ):
                continue
            if query:
                needle = query.casefold()
                matches_query = False
                for event in conv_events:
                    payload = event.payload or {}
                    for field in ("messageMasked", "answerMasked", "descriptionMasked", "userMessage", "aiReply", "text"):
                        val = payload.get(field)
                        if val and needle in str(val).casefold():
                            matches_query = True
                            break
                    if matches_query:
                        break
                if not matches_query:
                    continue
            if issue_type_id and not any(
                event.issue_type_id == issue_type_id for event in conv_events
            ):
                continue
            if route and not any(
                event.event_type == "route.selected"
                and str(event.payload.get("route")) == route
                for event in conv_events
            ):
                continue
            if model and not any(
                event.event_type == "usage.recorded"
                and str(event.payload.get("model") or "") == model
                for event in conv_events
            ):
                continue
            has_feedback_event = any(
                event.event_type == "feedback.recorded" for event in conv_events
            )
            if has_feedback is True and not has_feedback_event:
                continue
            if has_feedback is False and has_feedback_event:
                continue
            has_handoff_event = any(
                event.event_type.startswith("handoff.") for event in conv_events
            )
            if handoff is True and not has_handoff_event:
                continue
            if handoff is False and has_handoff_event:
                continue
            filtered_ids.append(cid)
        start = int(cursor or "0")
        page_ids = filtered_ids[start : start + limit]
        items = []
        for conv_id in page_ids:
            conv_events = grouped[conv_id]
            turns = [event for event in conv_events if event.event_type == "turn.received"]
            latest = max(conv_events, key=lambda item: item.occurred_at)
            turn_actor = next((event.actor_ref for event in turns if event.actor_ref), None)
            routes = {
                str(event.payload.get("route"))
                for event in conv_events
                if event.event_type == "route.selected" and event.payload.get("route")
            }
            turn_records = []
            for t_event in sorted(turns, key=lambda x: x.occurred_at):
                t_summary = _summarize_turn_events(t_event, conv_events)
                fb_reason = next(
                    (
                        item.payload.get("reason")
                        for item in conv_events
                        if item.event_type == "feedback.recorded"
                        and (
                            item.correlation_id == t_event.correlation_id
                            or (item.turn_id and item.turn_id == t_event.turn_id)
                        )
                        and item.payload.get("reason")
                    ),
                    None,
                )
                turn_records.append(
                    {
                        "turnId": t_event.turn_id,
                        "occurredAt": t_event.occurred_at.isoformat(),
                        "correlationId": t_event.correlation_id,
                        "actorRef": t_event.actor_ref or turn_actor or latest.actor_ref,
                        "userMessage": t_event.payload.get("messageMasked"),
                        "aiReply": t_summary.get("answerMasked"),
                        "model": t_summary.get("model"),
                        "issueTypeId": t_summary.get("issueTypeId"),
                        "route": t_summary.get("route"),
                        "faqKey": t_summary.get("faqKey"),
                        "documentIds": t_summary.get("documentIds") or [],
                        "feedbackRating": t_summary.get("feedbackRating"),
                        "feedbackReason": fb_reason,
                        "handoffStatus": t_summary.get("handoffStatus"),
                    }
                )
            items.append(
                {
                    "conversationId": conv_id,
                    "turnCount": len(turns),
                    "lastOccurredAt": latest.occurred_at.isoformat(),
                    "actorRef": turn_actor or latest.actor_ref,
                    "channelScope": latest.channel_scope,
                    "routes": sorted(routes),
                    "turns": turn_records,
                }
            )
        next_index = start + len(page_ids)
        return {
            "items": items,
            "nextCursor": str(next_index) if next_index < len(filtered_ids) else None,
            "hasMore": next_index < len(filtered_ids),
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
        allow_unmasked = (
            actor.has_capability("ops.conversations.unmasked")
            and unmask_reason is not None
            and len(unmask_reason.strip()) >= 3
        )
        events.sort(key=lambda item: item.occurred_at)
        owner_unit_ids = {
            issue_type.owner_unit_id
            for event in events
            if event.issue_type_id
            if (issue_type := self.taxonomy.get(event.issue_type_id)) is not None
        }
        turns = []
        for event in events:
            if event.event_type != "turn.received":
                continue
            related = [
                item
                for item in events
                if item.turn_id == event.turn_id and item.event_type != "turn.received"
            ]
            summary = _summarize_turn_events(event, events)
            message_hidden = bool(event.payload.get("messageHidden"))
            authorized_fragments = [
                {
                    "issueTypeId": item.issue_type_id,
                    "descriptionMasked": item.payload.get("descriptionMasked"),
                    "issueId": item.payload.get("issueId"),
                }
                for item in related
                if item.event_type == "issue.extracted"
                and item.payload.get("descriptionMasked")
            ]
            # Mixed-permission turns redact the shared user message; never fall
            # back to releasing foreign-unit business text via messageMasked.
            message_masked = None if message_hidden else event.payload.get("messageMasked")
            raw_ai_reply = next((str(item.payload.get("aiReply")) for item in related if item.payload.get("aiReply")), None)
            turns.append(
                {
                    "turnId": event.turn_id,
                    "occurredAt": event.occurred_at.isoformat(),
                    "correlationId": event.correlation_id,
                    "userMessage": event.payload.get("userMessage") if allow_unmasked else message_masked,
                    "message": event.payload.get("userMessage") if allow_unmasked else message_masked,
                    "messageMasked": message_masked,
                    "messageHidden": message_hidden,
                    "messageHiddenReason": event.payload.get("messageHiddenReason"),
                    "authorizedFragments": authorized_fragments,
                    "maskingPolicyVersion": event.payload.get("maskingPolicyVersion"),
                    "masked": not allow_unmasked,
                    **summary,
                    "aiReply": (raw_ai_reply or summary.get("answerMasked")) if allow_unmasked else summary.get("answerMasked"),
                    "events": [
                        {
                            "eventType": item.event_type,
                            "payload": item.payload if allow_unmasked else {
                                k: v for k, v in item.payload.items()
                                if k not in {"userMessage", "aiReply", "rawText"}
                            },
                            "issueTypeId": item.issue_type_id,
                        }
                        for item in related
                    ],
                }
            )
        return {
            "conversationId": conversation_id,
            "ownerUnitId": next(iter(owner_unit_ids)) if len(owner_unit_ids) == 1 else None,
            "unmaskAuthorized": allow_unmasked,
            "turns": turns,
        }

