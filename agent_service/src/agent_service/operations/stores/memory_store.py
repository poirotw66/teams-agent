from __future__ import annotations

from datetime import datetime
from threading import Lock

from ..contracts import OperationalEvent


class MemoryOperationalStore:
    def __init__(self) -> None:
        self._events: list[OperationalEvent] = []
        self._seen_event_ids: set[str] = set()
        self._lock = Lock()

    async def append(self, event: OperationalEvent) -> bool:
        with self._lock:
            if event.event_id in self._seen_event_ids:
                return False
            self._seen_event_ids.add(event.event_id)
            self._events.append(event)
            return True

    def _filter_events(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[OperationalEvent]:
        filtered = self._events
        if since is not None:
            filtered = [event for event in filtered if event.occurred_at >= since]
        if until is not None:
            filtered = [event for event in filtered if event.occurred_at <= until]
        return filtered

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]:
        with self._lock:
            filtered = self._filter_events(since=since, until=until)
            start = int(cursor or "0")
            page = filtered[start : start + limit]
            next_index = start + len(page)
            next_cursor = str(next_index) if next_index < len(filtered) else None
            return list(page), next_cursor

    async def count_by_type(self, event_type: str) -> int:
        with self._lock:
            return sum(1 for event in self._events if event.event_type == event_type)

    async def purge_expired(self) -> int:
        from ..retention import purge_expired_events

        with self._lock:
            kept, removed = purge_expired_events(self._events)
            if removed:
                self._events = kept
                self._seen_event_ids = {event.event_id for event in kept}
            return removed
