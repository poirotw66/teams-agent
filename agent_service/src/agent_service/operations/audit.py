from __future__ import annotations

import uuid
from typing import Protocol

from .audit_stores import FileAuditStore, FirestoreAuditStore, MemoryAuditStore
from .contracts import AuditEventRecord, utc_now
from .masking import redact_secrets
from .settings import OpsSettings


class AuditStore(Protocol):
    async def append(self, event: AuditEventRecord) -> None: ...

    async def list_events(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[AuditEventRecord], str | None]: ...


def build_audit_event(
    *,
    actor_id: str,
    actor_role: str,
    action: str,
    target_type: str,
    target_id: str,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
    reason: str | None = None,
    result: str = "SUCCESS",
    correlation_id: str | None = None,
    environment: str = "dev",
) -> AuditEventRecord:
    return AuditEventRecord(
        audit_id=str(uuid.uuid4()),
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=redact_secrets(before) if before else None,
        after=redact_secrets(after) if after else None,
        reason=reason,
        result=result,  # type: ignore[arg-type]
        correlation_id=correlation_id,
        occurred_at=utc_now(),
        environment=environment,  # type: ignore[arg-type]
    )


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
