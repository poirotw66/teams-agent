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
        self._file_offset: int = 0
        self._load()

    def _ensure_synced(self) -> None:
        self._sync_locked()

    def _sync_locked(self) -> None:
        if self._index_file.is_file():
            try:
                seen = json.loads(self._index_file.read_text(encoding="utf-8"))
                self._seen_event_ids.update(str(item) for item in seen)
            except Exception:
                pass
        if not self._events_file.is_file():
            self._file_offset = 0
            return

        stat = self._events_file.stat()
        file_size = stat.st_size
        if file_size < self._file_offset:
            self._events = []
            self._seen_event_ids.clear()
            self._file_offset = 0

        if file_size > self._file_offset:
            loaded_ids = {item.event_id for item in self._events}
            with self._events_file.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self._file_offset)
                new_lines = f.read()
                self._file_offset = f.tell()
            for line in new_lines.splitlines():
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    event = OperationalEvent.model_validate(json.loads(line_str))
                    self._seen_event_ids.add(event.event_id)
                    if event.event_id not in loaded_ids:
                        loaded_ids.add(event.event_id)
                        self._events.append(event)
                except Exception:
                    pass

    def _load(self) -> None:
        with self._lock:
            self._sync_locked()

    def _persist(self, event: OperationalEvent) -> None:
        with self._events_file.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")
            self._file_offset = handle.tell()
        self._index_file.write_text(
            json.dumps(sorted(self._seen_event_ids), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def append(self, event: OperationalEvent) -> bool:
        inserted = await super().append(event)
        if inserted:
            with self._lock:
                self._persist(event)
        return inserted

    async def purge_expired(self) -> int:
        removed = await super().purge_expired()
        if removed:
            with self._lock:
                self._events_file.write_text(
                    "\n".join(event.model_dump_json() for event in self._events) + "\n",
                    encoding="utf-8",
                )
                self._file_offset = self._events_file.stat().st_size
                self._index_file.write_text(
                    json.dumps(sorted(self._seen_event_ids), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        return removed
