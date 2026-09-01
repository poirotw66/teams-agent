from __future__ import annotations

from .access import ActorContext
from .contracts import OperationalEvent
from .taxonomy import TaxonomyRepository


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
    owner_unit_id = owner_unit_for_event(event, taxonomy)
    return actor.allows_owner_unit(owner_unit_id)


def filter_events_by_scope(
    events: list[OperationalEvent],
    actor: ActorContext,
    taxonomy: TaxonomyRepository,
) -> list[OperationalEvent]:
    return [
        event
        for event in events
        if event_in_actor_scope(event, actor, taxonomy)
    ]
