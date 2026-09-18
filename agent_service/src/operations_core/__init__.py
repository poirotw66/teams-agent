"""Shared operations contracts used by Agent, Backoffice, and Portal.

This package holds stable access, event, and masking types so Backoffice and
Portal do not need to import Agent runtime implementation modules for those
concerns.
"""

from __future__ import annotations

from operations_core.access import (
    CAPABILITIES,
    ActorContext,
    BackofficeRole,
)
from operations_core.contracts import (
    DEFAULT_TIMEZONE,
    MASKING_POLICY_VERSION,
    OperationalEvent,
    OperationalEventType,
    utc_now,
)
from operations_core.masking import MaskingResult, mask_text, redact_secrets
from operations_core.masking_rules import MaskingRulePack, resolve_masking_pack

__all__ = [
    "CAPABILITIES",
    "DEFAULT_TIMEZONE",
    "MASKING_POLICY_VERSION",
    "ActorContext",
    "BackofficeRole",
    "MaskingResult",
    "MaskingRulePack",
    "OperationalEvent",
    "OperationalEventType",
    "mask_text",
    "redact_secrets",
    "resolve_masking_pack",
    "utc_now",
]
