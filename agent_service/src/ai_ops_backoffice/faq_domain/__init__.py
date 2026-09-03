"""Phase 2 FAQ governance domain. No endpoint or runtime wiring lives here."""

from .audit_delivery import FaqAuditDeliveryPort
from .authorization import (
    AccessPolicyAuthorization,
    DenyUnknownTaxonomy,
    FaqAuthorizationPort,
    FaqTaxonomyPort,
)
from .errors import (
    FaqAuthorizationError,
    FaqDomainError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)
from .models import FaqContent, FaqRecord, FaqRuntimeSnapshot, FaqTestCase, FaqVersion
from .repository import FileFaqRepository, FirestoreFaqRepository, InMemoryFaqRepository
from .service import FaqDomainService

__all__ = [
    "AccessPolicyAuthorization",
    "DenyUnknownTaxonomy",
    "FaqAuditDeliveryPort",
    "FaqAuthorizationError",
    "FaqAuthorizationPort",
    "FaqContent",
    "FaqDomainError",
    "FaqDomainService",
    "FaqIdempotencyConflictError",
    "FaqNotFoundError",
    "FaqRecord",
    "FaqRuntimeSnapshot",
    "FaqTaxonomyPort",
    "FaqTestCase",
    "FaqTransitionError",
    "FaqValidationError",
    "FaqVersion",
    "FaqVersionConflictError",
    "FileFaqRepository",
    "FirestoreFaqRepository",
    "InMemoryFaqRepository",
]
