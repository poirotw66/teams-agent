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


def tenant_allows_event(actor: ActorContext, event: OperationalEvent) -> bool:
    """Tenant is a hard boundary for non-bypass roles."""
    if actor.role in _BYPASS_SCOPE_ROLES:
        return True
    actor_tenant = (actor.tenant_id or "").strip()
    event_tenant = (event.tenant_id or "").strip()
    if not actor_tenant:
        # Scoped principals must carry a tenant; missing binding denies access.
        return False
    if not event_tenant:
        return False
    return actor_tenant == event_tenant


def event_in_actor_scope(
    event: OperationalEvent,
    actor: ActorContext,
    taxonomy: TaxonomyRepository,
) -> bool:
    if not tenant_allows_event(actor, event):
        return False
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
    """Filter events with per-event authorization.

    Tenant is always enforced first for non-bypass roles.  Owner-unit checks
    apply per event.  Companion events without an owner unit may ride along
    only when they share the same ``turn_id`` and tenant as an explicitly
    authorized event — never the whole conversation.
    """
    if actor.role in _BYPASS_SCOPE_ROLES:
        return list(events)

    allowed_turns: set[str] = set()
    scoped: list[OperationalEvent] = []
    scoped_ids: set[str] = set()

    for event in events:
        if not tenant_allows_event(actor, event):
            continue
        owner_unit_id = owner_unit_for_event(event, taxonomy)
        if not owner_unit_id:
            continue
        if not actor.allows_owner_unit(owner_unit_id):
            continue
        scoped.append(event)
        scoped_ids.add(event.event_id)
        if event.turn_id:
            allowed_turns.add(event.turn_id)

    for event in events:
        if event.event_id in scoped_ids:
            continue
        if not tenant_allows_event(actor, event):
            continue
        # Never widen to foreign owner units via conversation membership.
        if owner_unit_for_event(event, taxonomy):
            continue
        if event.turn_id and event.turn_id in allowed_turns:
            scoped.append(event)
            scoped_ids.add(event.event_id)

    return scoped
