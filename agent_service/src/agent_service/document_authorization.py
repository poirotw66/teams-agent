"""Compatibility facade for unified document authorization.

Prefer ``operations_core.document_authorization`` for new code. This module
re-exports the shared helpers so existing Agent imports keep working during
ownership migration.
"""

from __future__ import annotations

from operations_core.document_authorization import (
    DocumentAccessDecision,
    DocumentAccessDeniedError,
    authorize_document_access,
    ensure_document_access,
)

__all__ = [
    "DocumentAccessDecision",
    "DocumentAccessDeniedError",
    "authorize_document_access",
    "ensure_document_access",
]
