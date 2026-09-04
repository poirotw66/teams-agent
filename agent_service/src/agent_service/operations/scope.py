from __future__ import annotations

from .access import ActorContext
from .contracts import OperationalEvent
from .taxonomy import TaxonomyRepository

# Cross-unit visibility for platform / AI / audit operators within an allowed
# tenant boundary (see CROSS_TENANT_ROLES for tenant policy).
CROSS_OWNER_UNIT_ROLES = frozenset({"SYSTEM_ADMIN", "AI_ADMIN", "AUDITOR"})

# Intentional cross-tenant access. AI_ADMIN is NOT included: model/prompt ops
# stay tenant-bound via actor.tenant_id. SYSTEM_ADMIN and AUDITOR may inspect
# every tenant for platform operations and audit.
CROSS_TENANT_ROLES = frozenset({"SYSTEM_ADMIN", "AUDITOR"})

_SHARED_MESSAGE_PAYLOAD_KEYS = frozenset({"messageMasked", "messageWasMasked"})
_MIXED_TURN_HIDDEN_REASON = "MIXED_OWNER_UNIT_TURN"


def owner_unit_for_event(
    event: OperationalEvent,
    taxonomy: TaxonomyRepository,
) -> str | None:
    if not event.issue_type_id:
        return None
    record = taxonomy.get(event.issue_type_id)
    return record.owner_unit_id if record else None


def actor_bypasses_tenant_boundary(actor: ActorContext) -> bool:
    """Return True when the role may read events across all tenants."""
    return actor.role in CROSS_TENANT_ROLES


def actor_bypasses_owner_unit_scope(actor: ActorContext) -> bool:
    """Return True when the role may read every owner unit inside allowed tenants."""
    return actor.role in CROSS_OWNER_UNIT_ROLES


def tenant_allows_event(actor: ActorContext, event: OperationalEvent) -> bool:
    """Tenant is a hard boundary unless the role is explicitly cross-tenant.

    Events with a missing tenant bind only to the synthetic lab tenant
    ``local-development`` so legacy fixtures remain readable without opening
    cross-tenant access for real tenants.
    """
    if actor_bypasses_tenant_boundary(actor):
        return True
    actor_tenant = (actor.tenant_id or "").strip()
    if not actor_tenant:
        return False
    event_tenant = (event.tenant_id or "").strip() or "local-development"
    return actor_tenant == event_tenant


def event_in_actor_scope(
    event: OperationalEvent,
    actor: ActorContext,
    taxonomy: TaxonomyRepository,
) -> bool:
    if not tenant_allows_event(actor, event):
        return False
    if actor_bypasses_owner_unit_scope(actor):
        return True
    owner_unit_id = owner_unit_for_event(event, taxonomy)
    if owner_unit_id:
        return actor.allows_owner_unit(owner_unit_id)
    return False


def _redact_shared_message(event: OperationalEvent) -> OperationalEvent:
    payload = {
        key: value
        for key, value in event.payload.items()
        if key not in _SHARED_MESSAGE_PAYLOAD_KEYS
    }
    payload["messageHidden"] = True
    payload["messageHiddenReason"] = _MIXED_TURN_HIDDEN_REASON
    return event.model_copy(update={"payload": payload})


def _carries_shared_user_message(event: OperationalEvent) -> bool:
    if event.event_type == "turn.received":
        return True
    return any(key in event.payload for key in _SHARED_MESSAGE_PAYLOAD_KEYS)


def filter_events_by_scope(
    events: list[OperationalEvent],
    actor: ActorContext,
    taxonomy: TaxonomyRepository,
) -> list[OperationalEvent]:
    """Filter events with per-event authorization.

    Tenant is always enforced first unless the role is in ``CROSS_TENANT_ROLES``.
    Owner-unit checks apply per event unless the role is in
    ``CROSS_OWNER_UNIT_ROLES``.

    Companion events without an owner unit may ride along only when they share
    the same ``turn_id`` or ``correlation_id`` (and tenant) as an explicitly
    authorized event — never the whole conversation.

    When a turn/correlation also contains owned events outside the actor's
    units (mixed-permission), shared user text such as ``messageMasked`` is
    redacted. Authorized issue events still expose per-case
    ``descriptionMasked`` fragments; callers must not reassemble the foreign
    unit's business content from the shared turn message.
    """
    if actor_bypasses_owner_unit_scope(actor) and actor_bypasses_tenant_boundary(actor):
        return list(events)

    if actor_bypasses_owner_unit_scope(actor):
        return [event for event in events if tenant_allows_event(actor, event)]

    allowed_turns: set[str] = set()
    allowed_correlations: set[str] = set()
    mixed_turns: set[str] = set()
    mixed_correlations: set[str] = set()
    scoped: list[OperationalEvent] = []
    scoped_ids: set[str] = set()

    for event in events:
        if not tenant_allows_event(actor, event):
            continue
        owner_unit_id = owner_unit_for_event(event, taxonomy)
        if not owner_unit_id:
            continue
        if actor.allows_owner_unit(owner_unit_id):
            scoped.append(event)
            scoped_ids.add(event.event_id)
            if event.turn_id:
                allowed_turns.add(event.turn_id)
            if event.correlation_id:
                allowed_correlations.add(event.correlation_id)
        else:
            if event.turn_id:
                mixed_turns.add(event.turn_id)
            if event.correlation_id:
                mixed_correlations.add(event.correlation_id)

    # Only turns/correlations that also have an authorized owned event are mixed.
    mixed_turns &= allowed_turns
    mixed_correlations &= allowed_correlations

    for event in events:
        if event.event_id in scoped_ids:
            continue
        if not tenant_allows_event(actor, event):
            continue
        # Never widen to foreign owner units via conversation membership.
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
        if (turn_mixed or correlation_mixed) and _carries_shared_user_message(event):
            scoped.append(_redact_shared_message(event))
        else:
            scoped.append(event)
        scoped_ids.add(event.event_id)

    return scoped
