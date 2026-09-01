from __future__ import annotations

import json
from pathlib import Path

from ..contracts import OperationalEvent
from .memory_store import MemoryOperationalStore


class FileOperationalStore(MemoryOperationalStore):
    def __init__(self, store_path: Path) -> None:
        super().__init__()
        self._store_path = store_path
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._events_file = self._store_path / "events.jsonl"
        self._index_file = self._store_path / "event_ids.json"
        self._load()

    def _load(self) -> None:
        if self._index_file.is_file():
            seen = json.loads(self._index_file.read_text(encoding="utf-8"))
            self._seen_event_ids.update(str(item) for item in seen)
        if not self._events_file.is_file():
            return
        for line in self._events_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = OperationalEvent.model_validate(json.loads(line))
            if event.event_id not in {item.event_id for item in self._events}:
                self._events.append(event)

    def _persist(self, event: OperationalEvent) -> None:
        with self._events_file.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")
        self._index_file.write_text(
            json.dumps(sorted(self._seen_event_ids), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def append(self, event: OperationalEvent) -> bool:
        inserted = await super().append(event)
        if inserted:
            self._persist(event)
        return inserted

    async def purge_expired(self) -> int:
        removed = await super().purge_expired()
        if removed:
            self._events_file.write_text(
                "\n".join(event.model_dump_json() for event in self._events) + "\n",
                encoding="utf-8",
            )
            self._index_file.write_text(
                json.dumps(sorted(self._seen_event_ids), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return removed
