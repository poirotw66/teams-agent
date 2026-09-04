from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .contracts import OperationalEvent, utc_now
from .masking import redact_secrets
from .policy_runtime import active_masking_policy_version
from .retention import retention_expiry
from .settings import OpsSettings


class OperationalStore(Protocol):
    async def append(self, event: OperationalEvent) -> bool: ...

    async def find_events(self, *, correlation_id: str) -> list[OperationalEvent]:
        ...

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]: ...


class EventIngestionService:
    def __init__(self, store: OperationalStore, settings: OpsSettings) -> None:
        self._store = store
        self._settings = settings

    async def ingest(self, event: OperationalEvent) -> bool:
        # This is the persistence boundary.  Emitters should mask at source, but
        # every event is defensively normalised here before any store receives it.
        # redact_secrets is idempotent, preserving retry/idempotency semantics.
        payload = redact_secrets(event.payload)
        active_policy = active_masking_policy_version()
        source_policy_version = event.masking_policy_version
        source_payload_policy = event.payload.get("maskingPolicyVersion")
        if (
            source_policy_version == active_policy
            and isinstance(source_payload_policy, str)
            and source_payload_policy != active_policy
        ):
            source_policy_version = source_payload_policy
        if source_policy_version != active_policy:
            payload["sourceMaskingPolicyVersion"] = source_policy_version
        # The persisted copy was cleaned at this boundary, irrespective of an
        # older producer's policy.  Keep the source version above for replay
        # provenance; this does not alter events already stored elsewhere.
        payload["maskingPolicyVersion"] = active_policy
        event = event.model_copy(
            update={
                "ingested_at": event.ingested_at or utc_now(),
                "environment": event.environment or self._settings.environment,  # type: ignore[arg-type]
                "retention_expires_at": event.retention_expires_at
                or retention_expiry(self._settings),
                "masking_policy_version": active_policy,
                "payload": payload,
            }
        )
        return await self._store.append(event)

    async def ingest_many(self, events: list[OperationalEvent]) -> int:
        inserted = 0
        for event in events:
            if await self.ingest(event):
                inserted += 1
        return inserted

    async def find_events(self, *, correlation_id: str) -> list[OperationalEvent]:
        return await self._store.find_events(correlation_id=correlation_id)
