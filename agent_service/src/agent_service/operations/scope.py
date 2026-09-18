"""Compatibility facade for operations scope helpers.

Prefer ``operations_core.scope`` for new code. This module re-exports the shared
predicates and taxonomy-backed event filters so existing Agent imports keep
working during ownership migration.
"""

from __future__ import annotations

from operations_core.scope import (
    CROSS_OWNER_UNIT_ROLES,
    CROSS_TENANT_ROLES,
    LOCAL_SANDBOX_TENANTS,
    TaxonomyLookup,
    TaxonomyOwnerUnit,
    actor_bypasses_owner_unit_scope,
    actor_bypasses_tenant_boundary,
    event_in_actor_scope,
    filter_events_by_scope,
    owner_unit_for_event,
    tenant_allows_event,
)

__all__ = [
    "CROSS_OWNER_UNIT_ROLES",
    "CROSS_TENANT_ROLES",
    "LOCAL_SANDBOX_TENANTS",
    "TaxonomyLookup",
    "TaxonomyOwnerUnit",
    "actor_bypasses_owner_unit_scope",
    "actor_bypasses_tenant_boundary",
    "event_in_actor_scope",
    "filter_events_by_scope",
    "owner_unit_for_event",
    "tenant_allows_event",
]
