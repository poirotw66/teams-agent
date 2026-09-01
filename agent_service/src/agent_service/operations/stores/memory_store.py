from __future__ import annotations

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

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[OperationalEvent], str | None]:
        with self._lock:
            start = int(cursor or "0")
            page = self._events[start : start + limit]
            next_index = start + len(page)
            next_cursor = str(next_index) if next_index < len(self._events) else None
            return list(page), next_cursor

    async def count_by_type(self, event_type: str) -> int:
        with self._lock:
            return sum(1 for event in self._events if event.event_type == event_type)
