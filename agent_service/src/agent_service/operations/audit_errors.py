"""Compatibility facade for audit write errors.

Prefer ``operations_core.audit_errors`` for new code. This module re-exports
``AuditWriteError`` so existing Agent imports keep working during ownership
migration.
"""

from __future__ import annotations

from operations_core.audit_errors import AuditWriteError

__all__ = ["AuditWriteError"]
