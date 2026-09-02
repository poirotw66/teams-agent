from __future__ import annotations

from .access import ActorContext
from .contracts import OperationalEvent
from .taxonomy import TaxonomyRepository

_BYPASS_SCOPE_ROLES = frozenset({"SYSTEM_ADMIN", "AI_ADMIN", "AUDITOR"})


def owner_unit_for_event(
    event: OperationalEvent,
    taxonomy: TaxonomyRepository,
) -> str | None:
    if not event.issue_type_id:
        return None
    record = taxonomy.get(event.issue_type_id)
    return record.owner_unit_id if record else None


def event_in_actor_scope(
    event: OperationalEvent,
    actor: ActorContext,
    taxonomy: TaxonomyRepository,
) -> bool:
    if actor.role in _BYPASS_SCOPE_ROLES:
        return True
    owner_unit_id = owner_unit_for_event(event, taxonomy)
    if owner_unit_id:
        return actor.allows_owner_unit(owner_unit_id)
    return False


def filter_events_by_scope(
    events: list[OperationalEvent],
    actor: ActorContext,
    taxonomy: TaxonomyRepository,
) -> list[OperationalEvent]:
    if actor.role in _BYPASS_SCOPE_ROLES:
        return list(events)

    allowed_conversations: set[str] = set()
    allowed_turns: set[str] = set()
    for event in events:
        owner_unit_id = owner_unit_for_event(event, taxonomy)
        if owner_unit_id and actor.allows_owner_unit(owner_unit_id):
            if event.conversation_id:
                allowed_conversations.add(event.conversation_id)
            if event.turn_id:
                allowed_turns.add(event.turn_id)

    scoped: list[OperationalEvent] = []
    for event in events:
        if event_in_actor_scope(event, actor, taxonomy):
            scoped.append(event)
            continue
        if event.conversation_id and event.conversation_id in allowed_conversations:
            scoped.append(event)
            continue
        if event.turn_id and event.turn_id in allowed_turns:
            scoped.append(event)
    return scoped
