from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..contracts import OperationalEvent
from ..stores.firestore_store import _firestore_document
from .firestore_journal import mutate_document
from .journal import EventConflict, fingerprint


class FirestoreDeliveryPrimary:
    """Transactional immutable projection; direct legacy writers must be retired."""

    def __init__(self, client: Any, collection: str) -> None:
        self._client = client
        self._collection = client.collection(collection)

    async def append(self, event: OperationalEvent) -> bool:
        def operation(old: dict[str, Any] | None) -> tuple[Any, bool]:
            if old is not None:
                if fingerprint(OperationalEvent.model_validate(old)) != fingerprint(event):
                    raise EventConflict()
                return None, False
            return _firestore_document(event), True
        return await mutate_document(
            self._client, self._collection.document(event.event_id), operation
        )

    async def list_events(
        self, *, limit: int = 100, cursor: str | None = None,
        since: datetime | None = None, until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self._collection.order_by("occurred_at")
        for op, value in ((">=", since), ("<=", until)):
            if value is not None:
                query = query.where(filter=FieldFilter("occurred_at", op, value))
        if cursor:
            snapshot = await self._collection.document(cursor).get()
            if snapshot.exists:
                query = query.start_after(snapshot)
        snapshots = [snapshot async for snapshot in query.limit(limit + 1).stream()]
        return (
            [OperationalEvent.model_validate(snapshot.to_dict()) for snapshot in snapshots[:limit]],
            snapshots[limit - 1].id if len(snapshots) > limit else None,
        )


class FileDeliveryPrimary:
    """Local development projection compatible with events.jsonl readers.

    Lock + fsynced replace prevents torn appends across local worker processes.
    The event-id index is derived, never used as evidence an event exists.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True, exist_ok=True)

    def _read(self) -> list[OperationalEvent]:
        path = self.path / "events.jsonl"
        if not path.exists():
            return []
        return [OperationalEvent.model_validate_json(line)
                for line in path.read_text().splitlines() if line.strip()]

    def _replace(self, name: str, data: str) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".delivery-", dir=self.path)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path / name)
            directory = os.open(self.path, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _append(self, event: OperationalEvent) -> bool:
        import fcntl

        with (self.path / ".delivery-primary.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            events = self._read()
            existing = next((item for item in events if item.event_id == event.event_id), None)
            if existing is not None and fingerprint(existing) != fingerprint(event):
                raise EventConflict()
            if existing is None:
                events.append(event)
                self._replace("events.jsonl", "\n".join(item.model_dump_json() for item in events) + "\n")
            self._replace("event_ids.json", json.dumps(sorted({item.event_id for item in events})))
            return existing is None

    async def append(self, event: OperationalEvent) -> bool:
        return await asyncio.to_thread(self._append, event)

    async def list_events(
        self, *, limit: int = 100, cursor: str | None = None,
        since: datetime | None = None, until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]:
        events = await asyncio.to_thread(self._read)
        filtered = [event for event in events
                    if (since is None or event.occurred_at >= since)
                    and (until is None or event.occurred_at <= until)]
        start = int(cursor or "0")
        page = filtered[start:start + limit]
        end = start + len(page)
        return page, str(end) if end < len(filtered) else None
