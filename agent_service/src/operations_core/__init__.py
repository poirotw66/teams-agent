"""Shared operations contracts used by Agent, Backoffice, and Portal.

This package holds stable access, audit protocol/builder, authorization, event,
masking, security-policy catalog, scope predicates, and taxonomy repository so
Backoffice and Portal do not need to import Agent runtime implementation
modules for those concerns.
"""

from __future__ import annotations

from operations_core.access import (
    CAPABILITIES,
    ActorContext,
    BackofficeRole,
)
from operations_core.audit import AuditStore, build_audit_event
from operations_core.audit_errors import AuditWriteError
from operations_core.contracts import (
    DEFAULT_TIMEZONE,
    MASKING_POLICY_VERSION,
    OperationalEvent,
    OperationalEventType,
    utc_now,
)
from operations_core.document_authorization import (
    DocumentAccessDecision,
    DocumentAccessDeniedError,
    authorize_document_access,
    ensure_document_access,
)
from operations_core.masking import MaskingResult, mask_text, redact_secrets
from operations_core.masking_rules import MaskingRulePack, resolve_masking_pack
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
from operations_core.security_policies import (
    SECURITY_POLICIES,
    SecurityPolicy,
    is_policy_id,
    known_policy_ids_in_text,
    policy_ids_in_text,
)
from operations_core.taxonomy import TaxonomyRepository

__all__ = [
    "CAPABILITIES",
    "CROSS_OWNER_UNIT_ROLES",
    "CROSS_TENANT_ROLES",
    "DEFAULT_TIMEZONE",
    "LOCAL_SANDBOX_TENANTS",
    "MASKING_POLICY_VERSION",
    "SECURITY_POLICIES",
    "ActorContext",
    "AuditStore",
    "AuditWriteError",
    "BackofficeRole",
    "DocumentAccessDecision",
    "DocumentAccessDeniedError",
    "MaskingResult",
    "MaskingRulePack",
    "OperationalEvent",
    "OperationalEventType",
    "SecurityPolicy",
    "TaxonomyLookup",
    "TaxonomyOwnerUnit",
    "TaxonomyRepository",
    "actor_bypasses_owner_unit_scope",
    "actor_bypasses_tenant_boundary",
    "authorize_document_access",
    "build_audit_event",
    "ensure_document_access",
    "event_in_actor_scope",
    "filter_events_by_scope",
    "is_policy_id",
    "known_policy_ids_in_text",
    "mask_text",
    "owner_unit_for_event",
    "policy_ids_in_text",
    "redact_secrets",
    "resolve_masking_pack",
    "tenant_allows_event",
    "utc_now",
]
