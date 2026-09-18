"""Compatibility facade for masking helpers.

Prefer ``operations_core.masking`` for new code. This module re-exports the
shared helpers so existing Agent imports keep working during ownership
migration.
"""

from __future__ import annotations

from operations_core.masking import (
    MASKING_POLICY_VERSION,
    ActiveMaskingPolicy,
    MaskingResult,
    mask_text,
    pseudonymous_actor_id,
    redact_secrets,
    register_active_masking_policy_provider,
)

__all__ = [
    "MASKING_POLICY_VERSION",
    "ActiveMaskingPolicy",
    "MaskingResult",
    "mask_text",
    "pseudonymous_actor_id",
    "redact_secrets",
    "register_active_masking_policy_provider",
]
