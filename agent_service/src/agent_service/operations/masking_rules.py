"""Compatibility facade for versioned masking rule packs.

Prefer ``operations_core.masking_rules`` for new code. This module re-exports
the shared types so existing Agent imports keep working during ownership
migration.
"""

from __future__ import annotations

from operations_core.masking_rules import (
    MASKING_RULE_PACKS,
    MaskingRulePack,
    apply_masking_pack,
    resolve_masking_pack,
)

__all__ = [
    "MASKING_RULE_PACKS",
    "MaskingRulePack",
    "apply_masking_pack",
    "resolve_masking_pack",
]
