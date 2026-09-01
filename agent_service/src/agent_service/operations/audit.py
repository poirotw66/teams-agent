from __future__ import annotations

import uuid
from typing import Protocol

from .contracts import AuditEventRecord, utc_now
from .masking import redact_secrets


class AuditStore(Protocol):
    async def append(self, event: AuditEventRecord) -> None: ...

    async def list_events(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[AuditEventRecord], str | None]: ...


class MemoryAuditStore:
    def __init__(self) -> None:
        self._events: list[AuditEventRecord] = []

    async def append(self, event: AuditEventRecord) -> None:
        self._events.append(event)

    async def list_events(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[AuditEventRecord], str | None]:
        start = int(cursor or "0")
        page = self._events[start : start + limit]
        next_index = start + len(page)
        next_cursor = str(next_index) if next_index < len(self._events) else None
        return page, next_cursor


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
