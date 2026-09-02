from __future__ import annotations


class AuditWriteError(Exception):
    """Raised when a high-risk operation cannot be audited (fail closed)."""
