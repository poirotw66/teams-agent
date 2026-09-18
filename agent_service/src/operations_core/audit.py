"""Shared audit protocol and event builder.

Store backends (memory, file, Firestore) and ``build_audit_store`` remain in
Agent; Backoffice and Portal depend on this protocol plus ``build_audit_event``
without importing Agent persistence wiring.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Protocol

from operations_core.contracts import AuditEventRecord, utc_now
from operations_core.masking import mask_text, redact_secrets


class AuditStore(Protocol):
    async def append(self, event: AuditEventRecord) -> None: ...

    async def list_events(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
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
    retention_expires_at: datetime | None = None,
) -> AuditEventRecord:
    expires_at = retention_expires_at or (utc_now() + timedelta(days=1095))
    return AuditEventRecord(
        audit_id=str(uuid.uuid4()),
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=redact_secrets(before) if before else None,
        after=redact_secrets(after) if after else None,
        # Reason is free text and is persisted alongside before/after, so it
        # follows the same credential policy.  Actor and target identifiers are
        # intentionally not transformed: they are required for audit attribution
        # and are not free-text fields.
        reason=mask_text(reason).text if reason is not None else None,
        result=result,  # type: ignore[arg-type]
        correlation_id=correlation_id,
        occurred_at=utc_now(),
        environment=environment,  # type: ignore[arg-type]
        retention_expires_at=expires_at,
    )


__all__ = [
    "AuditStore",
    "build_audit_event",
]
