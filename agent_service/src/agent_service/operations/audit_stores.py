from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from .contracts import AuditEventRecord

logger = logging.getLogger(__name__)


class MemoryAuditStore:
    def __init__(self) -> None:
        self._events: list[AuditEventRecord] = []
        self._lock = Lock()

    def _ensure_synced(self) -> None:
        pass

    async def append(self, event: AuditEventRecord) -> None:
        with self._lock:
            self._ensure_synced()
            self._events.append(event)

    async def list_events(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[AuditEventRecord], str | None]:
        with self._lock:
            self._ensure_synced()
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
        self._file_offset: int = 0
        self._load()

    def _ensure_synced(self) -> None:
        self._sync_locked()

    def _sync_locked(self) -> None:
        if not self._events_file.is_file():
            self._events = []
            self._file_offset = 0
            return
        stat = self._events_file.stat()
        file_size = stat.st_size
        if file_size < self._file_offset:
            self._events = []
            self._file_offset = 0
        if file_size > self._file_offset:
            loaded_ids = {item.audit_id for item in self._events}
            with self._events_file.open("rb") as f:
                f.seek(self._file_offset)
                while True:
                    line_bytes = f.readline()
                    if not line_bytes:
                        break
                    # If line doesn't end with newline, it is an incomplete tail line
                    if not line_bytes.endswith(b"\n"):
                        break
                    line_str = line_bytes.decode("utf-8", errors="replace").strip()
                    if line_str:
                        try:
                            event = AuditEventRecord.model_validate(json.loads(line_str))
                            if event.audit_id not in loaded_ids:
                                loaded_ids.add(event.audit_id)
                                self._events.append(event)
                        except Exception as exc:
                            logger.warning("Failed to parse audit event line: %s", exc)
                    self._file_offset = f.tell()

    def _load(self) -> None:
        with self._lock:
            self._sync_locked()

    def _persist(self, event: AuditEventRecord) -> None:
        with self._events_file.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")
            self._file_offset = handle.tell()

    async def append(self, event: AuditEventRecord) -> None:
        with self._lock:
            self._ensure_synced()
            if any(e.audit_id == event.audit_id for e in self._events):
                return
            self._events.append(event)
            self._persist(event)


class FirestoreAuditStore:
    def __init__(self, client: Any, collection: str) -> None:
        self._client = client
        self._collection = client.collection(collection)

    async def append(self, event: AuditEventRecord) -> None:
        document = self._collection.document(event.audit_id)
        snapshot = await document.get()
        if snapshot.exists:
            return
        payload = event.model_dump()
        for key in ("occurred_at", "retention_expires_at"):
            value = payload.get(key)
            if isinstance(value, str):
                payload[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        await document.set(payload)

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
        next_cursor = snapshots[limit - 1].id if len(snapshots) > limit > 0 else None
        return events, next_cursor
