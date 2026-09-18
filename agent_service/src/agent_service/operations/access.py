"""Compatibility facade for operations access contracts.

Prefer ``operations_core.access`` for new code. This module re-exports the shared
types so existing Agent imports keep working during ownership migration.
"""

from __future__ import annotations

from operations_core.access import CAPABILITIES, ActorContext, BackofficeRole

__all__ = [
    "CAPABILITIES",
    "ActorContext",
    "BackofficeRole",
]
