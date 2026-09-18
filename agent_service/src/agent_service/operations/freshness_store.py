"""Compatibility facade for FreshnessStore.

Prefer ``operations_core.freshness_store`` for new code. This module re-exports
the shared store so existing Agent imports keep working during ownership
migration.
"""

from __future__ import annotations

from operations_core.freshness_store import FreshnessStore

__all__ = ["FreshnessStore"]
