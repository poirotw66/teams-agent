"""Compatibility facade for the issue taxonomy repository.

Prefer ``operations_core.taxonomy`` for new code. This module re-exports
``TaxonomyRepository`` so existing Agent imports keep working during ownership
migration.
"""

from __future__ import annotations

from operations_core.taxonomy import TaxonomyRepository

__all__ = [
    "TaxonomyRepository",
]
