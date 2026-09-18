"""Assemble conversation detail turn payloads."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext
from operations_core.contracts import OperationalEvent
from operations_core.taxonomy import TaxonomyRepository

from .query_helpers import _summarize_turn_events


def _merge_source_refs_into_summary(
    summary: dict[str, Any],
    source_refs: list[dict[str, Any]],
) -> None:
    summary["sourceRefs"] = source_refs
    for source_ref in source_refs:
        for summary_key, ref_key in (
            ("documentIds", "documentId"),
            ("sourcePaths", "sourcePath"),
            ("releaseIds", "releaseId"),
        ):
            value = source_ref.get(ref_key)
            if value and value not in (summary.get(summary_key) or []):
                summary.setdefault(summary_key, []).append(value)


def _build_detail_turn(
    event: OperationalEvent,
    events: list[OperationalEvent],
    *,
    allow_unmasked: bool,
    source_trace: Any | None,
) -> dict[str, Any]:
    related = [
        item
        for item in events
        if item.turn_id == event.turn_id and item.event_type != "turn.received"
    ]
    summary = _summarize_turn_events(event, events)
    source_refs = (
        source_trace.references_for_events(related) if source_trace is not None else []
    )
    _merge_source_refs_into_summary(summary, source_refs)
    message_hidden = bool(event.payload.get("messageHidden"))
    authorized_fragments = [
        {
            "issueTypeId": item.issue_type_id,
            "descriptionMasked": item.payload.get("descriptionMasked"),
            "issueId": item.payload.get("issueId"),
        }
        for item in related
        if item.event_type == "issue.extracted" and item.payload.get("descriptionMasked")
    ]
    # Mixed-permission turns redact the shared user message; never fall
    # back to releasing foreign-unit business text via messageMasked.
    message_masked = None if message_hidden else event.payload.get("messageMasked")
    raw_ai_reply = next(
        (str(item.payload.get("aiReply")) for item in related if item.payload.get("aiReply")),
        None,
    )
    return {
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
        "aiReply": (
            (raw_ai_reply or summary.get("answerMasked"))
            if allow_unmasked
            else summary.get("answerMasked")
        ),
        "events": [
            {
                "eventType": item.event_type,
                "payload": item.payload
                if allow_unmasked
                else {
                    key: value
                    for key, value in item.payload.items()
                    if key not in {"userMessage", "aiReply", "rawText"}
                },
                "issueTypeId": item.issue_type_id,
            }
            for item in related
        ],
    }


def build_conversation_detail_payload(
    *,
    conversation_id: str,
    events: list[OperationalEvent],
    actor: ActorContext,
    taxonomy: TaxonomyRepository,
    source_trace: Any | None,
    unmask_reason: str | None,
) -> dict[str, Any]:
    allow_unmasked = (
        actor.has_capability("ops.conversations.unmasked")
        and unmask_reason is not None
        and len(unmask_reason.strip()) >= 3
    )
    events = sorted(events, key=lambda item: item.occurred_at)
    owner_unit_ids = {
        issue_type.owner_unit_id
        for event in events
        if event.issue_type_id
        if (issue_type := taxonomy.get(event.issue_type_id)) is not None
    }
    turns = [
        _build_detail_turn(
            event,
            events,
            allow_unmasked=allow_unmasked,
            source_trace=source_trace,
        )
        for event in events
        if event.event_type == "turn.received"
    ]
    return {
        "conversationId": conversation_id,
        "ownerUnitId": next(iter(owner_unit_ids)) if len(owner_unit_ids) == 1 else None,
        "unmaskAuthorized": allow_unmasked,
        "dataState": "UNMASKED_WITH_REASON" if allow_unmasked else "MASKED",
        "turns": turns,
    }
