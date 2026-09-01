from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import AuditEventRecord


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


class FileAuditStore(MemoryAuditStore):
    def __init__(self, store_path: Path) -> None:
        super().__init__()
        self._store_path = store_path
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._events_file = self._store_path / "audit_events.jsonl"
        self._load()

    def _load(self) -> None:
        if not self._events_file.is_file():
            return
        for line in self._events_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = AuditEventRecord.model_validate(json.loads(line))
            self._events.append(event)

    def _persist(self, event: AuditEventRecord) -> None:
        with self._events_file.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")

    async def append(self, event: AuditEventRecord) -> None:
        await super().append(event)
        self._persist(event)


class FirestoreAuditStore:
    def __init__(self, client: Any, collection: str) -> None:
        self._collection = client.collection(collection)

    async def append(self, event: AuditEventRecord) -> None:
        document = self._collection.document(event.audit_id)
        snapshot = await document.get()
        if snapshot.exists:
            return
        await document.set(event.model_dump(mode="json"))

    async def list_events(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[AuditEventRecord], str | None]:
        query = self._collection.order_by("occurred_at")
        if cursor:
            cursor_doc = await self._collection.document(cursor).get()
            if cursor_doc.exists:
                query = query.start_after(cursor_doc)
        snapshots = [item async for item in query.limit(limit + 1).stream()]
        events = [AuditEventRecord.model_validate(item.to_dict()) for item in snapshots[:limit]]
        next_cursor = snapshots[limit].id if len(snapshots) > limit else None
        return events, next_cursor
