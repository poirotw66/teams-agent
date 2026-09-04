from __future__ import annotations

import time
from datetime import datetime
from typing import Protocol

from ..contracts import OperationalEvent
from ..delivery.file_journal import FileJournal
from ..delivery.journal import Journal
from ..delivery.worker import DeliveryWorker
from .memory_store import MemoryOperationalStore


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


class CompositeOperationalStore:
    def __init__(
        self,
        primary: OperationalStore,
        sinks: list[object] | None = None,
        *,
        journal: Journal | None = None,
        sink_names: list[str] | None = None,
        inline_sinks: bool = True,
        worker_options: dict[str, float] | None = None,
    ) -> None:
        self._primary = primary
        self._sinks = sinks or []
        if journal is None:
            if type(primary) is not MemoryOperationalStore:
                raise ValueError("persistent_composite_store_requires_a_durable_journal")
            journal = FileJournal(None)
        names = sink_names or [
            f"{type(sink).__module__}.{type(sink).__qualname__}:{index}"
            for index, sink in enumerate(self._sinks)
        ]
        if len(names) != len(self._sinks) or len(set(names)) != len(names):
            raise ValueError("sink_names_must_be_unique_and_stable")
        if any(not name or name == "__primary__" for name in names):
            raise ValueError("invalid_sink_name")
        self._sink_map = dict(zip(names, self._sinks, strict=True))
        self._journal = journal
        self._inline_sinks = inline_sinks
        self.delivery_worker = DeliveryWorker(
            journal, primary, self._sink_map, **(worker_options or {})
        )

    async def append(self, event: OperationalEvent) -> bool:
        accepted = await self._journal.put(
            event, list(self._sink_map), self.delivery_worker.clock()
        )
        await self.delivery_worker.deliver_event(
            event.event_id, include_sinks=self._inline_sinks
        )
        return accepted

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]:
        return await self._primary.list_events(
            limit=limit,
            cursor=cursor,
            since=since,
            until=until,
        )

    async def find_events(self, *, correlation_id: str) -> list[OperationalEvent]:
        return await self._primary.find_events(correlation_id=correlation_id)

    async def delivery_stats(self) -> dict[str, object]:
        return await self._journal.stats(time.time())

    async def reconcile(self) -> int:
        return await self.delivery_worker.reconcile_primary()

    async def purge_expired(self) -> int:
        purge = getattr(self._primary, "purge_expired", None)
        return await purge() if purge else 0
