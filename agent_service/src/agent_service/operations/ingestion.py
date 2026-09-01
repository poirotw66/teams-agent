from __future__ import annotations

from typing import Protocol

from .contracts import OperationalEvent, utc_now
from .retention import retention_expiry
from .settings import OpsSettings


class OperationalStore(Protocol):
    async def append(self, event: OperationalEvent) -> bool: ...

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[OperationalEvent], str | None]: ...


class EventIngestionService:
    def __init__(self, store: OperationalStore, settings: OpsSettings) -> None:
        self._store = store
        self._settings = settings

    async def ingest(self, event: OperationalEvent) -> bool:
        event = event.model_copy(
            update={
                "ingested_at": event.ingested_at or utc_now(),
                "environment": event.environment or self._settings.environment,  # type: ignore[arg-type]
                "retention_expires_at": event.retention_expires_at
                or retention_expiry(self._settings),
            }
        )
        return await self._store.append(event)

    async def ingest_many(self, events: list[OperationalEvent]) -> int:
        inserted = 0
        for event in events:
            if await self.ingest(event):
                inserted += 1
        return inserted
