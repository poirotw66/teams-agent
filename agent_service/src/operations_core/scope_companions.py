"""Companion-event attachment for scoped operational event filtering."""

from __future__ import annotations

from operations_core.access import ActorContext
from operations_core.contracts import OperationalEvent

from .scope import (
    TaxonomyLookup,
    owner_unit_for_event,
    tenant_allows_event,
)

_SHARED_MESSAGE_PAYLOAD_KEYS = frozenset({"messageMasked", "messageWasMasked"})
_MIXED_TURN_HIDDEN_REASON = "MIXED_OWNER_UNIT_TURN"


def redact_shared_message(event: OperationalEvent) -> OperationalEvent:
    payload = {
        key: value
        for key, value in event.payload.items()
        if key not in _SHARED_MESSAGE_PAYLOAD_KEYS
    }
    payload["messageHidden"] = True
    payload["messageHiddenReason"] = _MIXED_TURN_HIDDEN_REASON
    return event.model_copy(update={"payload": payload})


def carries_shared_user_message(event: OperationalEvent) -> bool:
    if event.event_type == "turn.received":
        return True
    return any(key in event.payload for key in _SHARED_MESSAGE_PAYLOAD_KEYS)


def append_companion_events(
    *,
    events: list[OperationalEvent],
    actor: ActorContext,
    taxonomy: TaxonomyLookup,
    scoped: list[OperationalEvent],
    scoped_ids: set[str],
    allowed_turns: set[str],
    allowed_correlations: set[str],
    mixed_turns: set[str],
    mixed_correlations: set[str],
) -> None:
    for event in events:
        if event.event_id in scoped_ids:
            continue
        if not tenant_allows_event(actor, event):
            continue
        if owner_unit_for_event(event, taxonomy):
            continue
        same_turn = bool(event.turn_id and event.turn_id in allowed_turns)
        same_correlation = bool(
            event.correlation_id and event.correlation_id in allowed_correlations
        )
        if not (same_turn or same_correlation):
            continue
        turn_mixed = bool(event.turn_id and event.turn_id in mixed_turns)
        correlation_mixed = bool(
            event.correlation_id and event.correlation_id in mixed_correlations
        )
        if (turn_mixed or correlation_mixed) and carries_shared_user_message(event):
            scoped.append(redact_shared_message(event))
        else:
            scoped.append(event)
        scoped_ids.add(event.event_id)
