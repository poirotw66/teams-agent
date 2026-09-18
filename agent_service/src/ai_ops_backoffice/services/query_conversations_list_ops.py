"""Assemble conversation list items and turn summaries."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from operations_core.contracts import OperationalEvent

from .query_conversations_filters import conversation_matches_filters, matched_turn_for_filters
from .query_helpers import _summarize_turn_events


def group_events_by_conversation(
    events: list[OperationalEvent],
) -> dict[str, list[OperationalEvent]]:
    grouped: dict[str, list[OperationalEvent]] = defaultdict(list)
    for event in events:
        if event.conversation_id:
            grouped[event.conversation_id].append(event)
    return grouped


def select_conversation_page(
    grouped: dict[str, list[OperationalEvent]],
    *,
    conversation_id: str | None,
    channel_scope: str | None,
    user_filter: str | None,
    query: str | None,
    source: str | None,
    issue_type_id: str | None,
    route: str | None,
    model: str | None,
    has_feedback: bool | None,
    handoff: bool | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[str], list[str], int]:
    conversation_ids = sorted(
        grouped,
        key=lambda cid: max(item.occurred_at for item in grouped[cid]),
        reverse=True,
    )
    filtered_ids = [
        cid
        for cid in conversation_ids
        if conversation_matches_filters(
            grouped[cid],
            conversation_id=conversation_id,
            cid=cid,
            channel_scope=channel_scope,
            user_filter=user_filter,
            query=query,
            source=source,
            issue_type_id=issue_type_id,
            route=route,
            model=model,
            has_feedback=has_feedback,
            handoff=handoff,
        )
    ]
    start = int(cursor or "0")
    return filtered_ids, filtered_ids[start : start + limit], start


def build_conversation_turn_records(
    conv_events: list[OperationalEvent],
    *,
    source_trace: Any | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    turns = [event for event in conv_events if event.event_type == "turn.received"]
    latest = max(conv_events, key=lambda item: item.occurred_at)
    turn_actor = next((event.actor_ref for event in turns if event.actor_ref), None)
    turn_records: list[dict[str, Any]] = []
    turn_payloads: dict[str, dict[str, Any]] = {}
    for t_event in sorted(turns, key=lambda item: item.occurred_at):
        turn_payloads[str(t_event.turn_id)] = t_event.payload or {}
        t_summary = _summarize_turn_events(t_event, conv_events)
        source_events = [
            item
            for item in conv_events
            if item.event_type in {"knowledge.retrieved", "knowledge.answered"}
            and (
                item.turn_id == t_event.turn_id
                or (not item.turn_id and item.correlation_id == t_event.correlation_id)
            )
        ]
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
    return turn_records, turn_payloads


def build_conversation_list_item(
    conv_id: str,
    conv_events: list[OperationalEvent],
    *,
    source_trace: Any | None,
    query: str | None,
    source: str | None,
    issue_type_id: str | None,
    route: str | None,
    model: str | None,
    has_feedback: bool | None,
    handoff: bool | None,
    user_filter: str | None,
) -> dict[str, Any]:
    turns = [event for event in conv_events if event.event_type == "turn.received"]
    latest = max(conv_events, key=lambda item: item.occurred_at)
    turn_actor = next((event.actor_ref for event in turns if event.actor_ref), None)
    routes = {
        str(event.payload.get("route"))
        for event in conv_events
        if event.event_type == "route.selected" and event.payload.get("route")
    }
    turn_records, turn_payloads = build_conversation_turn_records(
        conv_events,
        source_trace=source_trace,
    )
    matched_turn_id, matched_turn_reasons = matched_turn_for_filters(
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
        {str(turn["ticketId"]) for turn in turn_records if turn.get("ticketId")}
        | {
            str(event.payload.get("ticketId"))
            for event in conv_events
            if event.event_type == "ticket.created" and event.payload.get("ticketId")
        }
    )
    conv_ticket_status = next(
        (turn["ticketStatus"] for turn in reversed(turn_records) if turn.get("ticketStatus")),
        None,
    )
    conv_handoff_status = next(
        (turn["handoffStatus"] for turn in reversed(turn_records) if turn.get("handoffStatus")),
        None,
    )
    return {
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


def attach_conversation_freshness(
    *,
    tracker: Any | None,
    actor: Any,
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if tracker is None:
        return None
    now_dt = tracker.now() if hasattr(tracker, "now") else datetime.now(timezone.utc)
    tenant_id = getattr(actor, "tenant_id", None)
    tracker.record_stage_event(
        "conversations",
        "CONVERSATION_LIST_RENDERED",
        at=now_dt,
        tenant_id=tenant_id,
    )
    for item in items:
        for turn in item.get("turns") or []:
            corr_id = turn.get("correlationId")
            if corr_id:
                tracker.record_stage_event(
                    corr_id,
                    "CONVERSATION_LIST_RENDERED",
                    at=now_dt,
                    tenant_id=tenant_id,
                )
    return tracker.compute_freshness(
        resource_type="conversations",
        watermark=None,
        tenant_id=tenant_id,
    ).model_dump(mode="json")
