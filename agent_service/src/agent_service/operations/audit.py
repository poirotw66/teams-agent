"""Compatibility facade for audit protocol, builder, and store factory.

Prefer ``operations_core.audit`` for ``AuditStore`` and ``build_audit_event``.
Store implementations and ``build_audit_store`` remain Agent-owned.
"""

from __future__ import annotations

from operations_core.audit import AuditStore, build_audit_event

from .audit_stores import FileAuditStore, FirestoreAuditStore, MemoryAuditStore
from .settings import OpsSettings

__all__ = [
    "AuditStore",
    "build_audit_event",
    "build_audit_store",
]


def build_audit_store(
    settings: OpsSettings,
) -> MemoryAuditStore | FileAuditStore | FirestoreAuditStore:
    mode = settings.audit_store_mode.upper()
    if mode == "FILE":
        audit_path = settings.store_path.parent / "audit"
        return FileAuditStore(audit_path)
    if mode == "FIRESTORE":
        from .stores.firestore_store import build_firestore_client

        client = build_firestore_client(settings.firestore_project, settings.firestore_database)
        return FirestoreAuditStore(client, settings.audit_firestore_collection)
    return MemoryAuditStore()
