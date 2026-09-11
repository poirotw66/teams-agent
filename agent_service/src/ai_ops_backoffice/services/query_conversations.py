"""Conversation list/detail queries for the AI Ops backoffice."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent
from agent_service.operations.scope import filter_events_by_scope

from .query_helpers import _summarize_turn_events


def _matched_turn_for_filters(
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

    active_filters: list[tuple[str, Callable[[dict[str, Any], dict[str, Any]], bool]]] = []

    if query:
        needle = query.casefold()

        def query_matches(turn: dict[str, Any], payload: dict[str, Any]) -> bool:
            values = [
                turn.get("userMessage"),
                turn.get("aiReply"),
                turn.get("ticketId"),
                *(payload.get(field) for field in (
                    "messageMasked",
                    "answerMasked",
                    "descriptionMasked",
                    "userMessage",
                    "aiReply",
                    "text",
                    "ticketId",
                )),
            ]
            return any(value and needle in str(value).casefold() for value in values)

        active_filters.append(("query", query_matches))

    if source:
        needle = source.casefold()

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

        active_filters.append(("source", source_matches))

    if issue_type_id:
        active_filters.append(("issue_type", lambda turn, _payload: turn.get("issueTypeId") == issue_type_id))
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
                            matches_query = True
                            break
                    if matches_query:
                        break
                if not matches_query:
                    continue
            if source:
                needle = source.casefold()
                matches_source = False
                for event in conv_events:
                    payload = event.payload or {}
                    for field in ("documentId", "sourcePath", "faqKey", "releaseId"):
                        val = payload.get(field)
                        if val and needle in str(val).casefold():
                            matches_source = True
                            break
                    if not matches_source and "citations" in payload:
                        for cit in payload.get("citations") or []:
                            if isinstance(cit, dict):
                                if any(
                                    needle in str(cit.get(k) or "").casefold()
                                    for k in ("documentId", "sourcePath", "title", "chunkId")
                                ):
                                    matches_source = True
                                    break
                    if matches_source:
                        break
                if not matches_source:
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
            turn_payloads: dict[str, dict[str, Any]] = {}
            for t_event in sorted(turns, key=lambda x: x.occurred_at):
                turn_payloads[str(t_event.turn_id)] = t_event.payload or {}
                t_summary = _summarize_turn_events(t_event, conv_events)
                source_events = [
                    item
                    for item in conv_events
                    if item.event_type in {"knowledge.retrieved", "knowledge.answered"}
                    and (
                        item.turn_id == t_event.turn_id
                        or (
                            not item.turn_id
                            and item.correlation_id == t_event.correlation_id
                        )
                    )
                ]
                source_trace = getattr(self, "_source_trace", None)
                t_source_refs = (
                    source_trace.references_for_events(source_events)
                    if source_trace is not None
                    else []
                )
                for source_ref in t_source_refs:
                    for summary_key, ref_key in (
                        ("documentIds", "documentId"),
                        ("sourcePaths", "sourcePath"),
                        ("releaseIds", "releaseId"),
                    ):
                        value = source_ref.get(ref_key)
                        if value and value not in (t_summary.get(summary_key) or []):
                            t_summary.setdefault(summary_key, []).append(value)
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
                        "sourcePaths": t_summary.get("sourcePaths") or [],
                        "sourceRefs": t_source_refs,
                        "feedbackRating": t_summary.get("feedbackRating"),
                        "feedbackReason": fb_reason,
                        "resolvedStatus": t_summary.get("resolvedStatus"),
                        "handoffStatus": t_summary.get("handoffStatus"),
                        "ticketId": t_summary.get("ticketId"),
                        "ticketStatus": t_summary.get("ticketStatus"),
                        "ticketBackend": t_summary.get("ticketBackend"),
                    }
                )
            matched_turn_id, matched_turn_reasons = _matched_turn_for_filters(
                turn_records,
                turn_payloads,
                query=query,
                source=source,
                issue_type_id=issue_type_id,
                route=route,
                model=model,
                has_feedback=has_feedback,
                handoff=handoff,
                user_filter=user_filter,
            )
            conv_ticket_ids = sorted(
                {
                    str(t["ticketId"])
                    for t in turn_records
                    if t.get("ticketId")
                }
                | {
                    str(event.payload.get("ticketId"))
                    for event in conv_events
                    if event.event_type == "ticket.created" and event.payload.get("ticketId")
                }
            )
            conv_ticket_status = next(
                (
                    t["ticketStatus"]
                    for t in reversed(turn_records)
                    if t.get("ticketStatus")
                ),
                None,
            )
            conv_handoff_status = next(
                (
                    t["handoffStatus"]
                    for t in reversed(turn_records)
                    if t.get("handoffStatus")
                ),
                None,
            )
            items.append(
                {
                    "conversationId": conv_id,
                    "turnCount": len(turns),
                    "lastOccurredAt": latest.occurred_at.isoformat(),
                    "actorRef": turn_actor or latest.actor_ref,
                    "channelScope": latest.channel_scope,
                    "routes": sorted(routes),
                    "ticketIds": conv_ticket_ids,
                    "ticketCount": len(conv_ticket_ids),
                    "ticketStatus": conv_ticket_status,
                    "handoffStatus": conv_handoff_status,
                    "matchedTurnId": matched_turn_id,
                    "matchedTurnReasons": matched_turn_reasons,
                    "turns": turn_records,
                }
            )
        next_index = start + len(page_ids)
        latest_event_at = None
        if events:
            latest_event_at = max((event.occurred_at for event in events), default=None)
        freshness_meta = None
        tracker = getattr(self, "_freshness_tracker", None)
        if tracker is not None:
            # Prefer ingest/aggregation completion; raw occurred_at alone is not lag.
            if latest_event_at is not None:
                tracker.record_stage_event(
                    "conversations-list",
                    "EVENT_INGESTED",
                    at=latest_event_at,
                )
            freshness_meta = tracker.compute_freshness(
                resource_type="conversations",
                watermark=None,
            ).model_dump(mode="json")
        return {
            "items": items,
            "nextCursor": str(next_index) if next_index < len(filtered_ids) else None,
            "hasMore": next_index < len(filtered_ids),
            "freshness": freshness_meta,
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
            source_trace = getattr(self, "_source_trace", None)
            summary["sourceRefs"] = (
                source_trace.references_for_events(related)
                if source_trace is not None
                else []
            )
            for source_ref in summary["sourceRefs"]:
                for summary_key, ref_key in (
                    ("documentIds", "documentId"),
                    ("sourcePaths", "sourcePath"),
                    ("releaseIds", "releaseId"),
                ):
                    value = source_ref.get(ref_key)
                    if value and value not in (summary.get(summary_key) or []):
                        summary.setdefault(summary_key, []).append(value)
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
                    "dataState": "UNMASKED_WITH_REASON" if allow_unmasked else "MASKED",
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
            "dataState": "UNMASKED_WITH_REASON" if allow_unmasked else "MASKED",
            "turns": turns,
        }
