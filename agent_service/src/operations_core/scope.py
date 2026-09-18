"""Pure operations scope constants and tenant/owner-unit predicates.

Taxonomy-backed filtering stays in ``agent_service.operations.scope`` until
TaxonomyRepository ownership moves.
"""

from __future__ import annotations

from operations_core.access import ActorContext
from operations_core.contracts import OperationalEvent

# Cross-unit visibility for platform / AI / audit operators within an allowed
# tenant boundary (see CROSS_TENANT_ROLES for tenant policy).
CROSS_OWNER_UNIT_ROLES = frozenset({"SYSTEM_ADMIN", "AI_ADMIN", "AUDITOR"})

# Intentional cross-tenant access. AI_ADMIN is NOT included: model/prompt ops
# stay tenant-bound via actor.tenant_id. SYSTEM_ADMIN and AUDITOR may inspect
# every tenant for platform operations and audit.
CROSS_TENANT_ROLES = frozenset({"SYSTEM_ADMIN", "AUDITOR"})

# Lab / local tenants that share a single development boundary.
# HEADER auth defaults to "default" (Portal/SourceRecord alignment); missing
# event tenants bind to "local-development". Treat both as equivalent sandboxes
# so seeded ops fixtures remain readable without opening real-tenant access.
LOCAL_SANDBOX_TENANTS = frozenset({
    "default",
    "local-development",
    "00000000-0000-0000-0000-0000000000001",
})


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
    cross-tenant access for real tenants. Actors on any ``LOCAL_SANDBOX_TENANTS``
    id may read those lab events.
    """
    if actor_bypasses_tenant_boundary(actor):
        return True
    actor_tenant = (actor.tenant_id or "").strip()
    if not actor_tenant:
        return False
    event_tenant = (event.tenant_id or "").strip() or "local-development"
    return (
        actor_tenant == event_tenant
        or (actor_tenant in LOCAL_SANDBOX_TENANTS and event_tenant in LOCAL_SANDBOX_TENANTS)
    )
