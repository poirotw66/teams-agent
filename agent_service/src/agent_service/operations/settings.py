"""Compatibility facade for OpsSettings.

Prefer ``operations_core.settings`` for new code. This module re-exports the
shared settings type so existing Agent imports keep working during ownership
migration.
"""

from __future__ import annotations

from operations_core.settings import OpsSettings

__all__ = ["OpsSettings"]
