from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
from pathlib import Path

from ..contracts import OperationalEvent, utc_now
from .memory_store import MemoryOperationalStore

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _cross_process_file_lock(lock_file_path: Path):
    lock_file = lock_file_path.open("a+")
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except (OSError, AttributeError):  # pragma: no cover - non-POSIX fallback
            pass
        yield
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except (OSError, AttributeError):  # pragma: no cover
            pass
        lock_file.close()


class FileOperationalStore(MemoryOperationalStore):
    def __init__(self, store_path: Path) -> None:
        super().__init__()
        self._store_path = store_path
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._events_file = self._store_path / "events.jsonl"
        self._index_file = self._store_path / "event_ids.json"
        self._lock_file = self._store_path / ".events.lock"
        self._file_offset: int = 0
        self._file_inode: int | None = None
        self._load()

    def _cross_process_lock(self):
        return _cross_process_file_lock(self._lock_file)

    def _ensure_synced(self) -> None:
        self._sync_locked()

    def _sync_locked(self) -> None:
        if self._index_file.is_file():
            try:
                seen = json.loads(self._index_file.read_text(encoding="utf-8"))
                self._seen_event_ids.update(str(item) for item in seen)
            except Exception as exc:
                logger.warning("Failed to read event index file: %s", exc)
        if not self._events_file.is_file():
            self._file_offset = 0
            self._file_inode = None
            return

        stat = self._events_file.stat()
        file_size = stat.st_size
        file_inode = getattr(stat, "st_ino", None)

        # Detect truncation or file replacement
        if file_size < self._file_offset or (
            self._file_inode is not None and file_inode != self._file_inode
        ):
            self._events = []
            self._seen_event_ids.clear()
            self._file_offset = 0
        self._file_inode = file_inode

        if file_size > self._file_offset:
            loaded_ids = {item.event_id for item in self._events}
            with self._events_file.open("rb") as f:
                f.seek(self._file_offset)
                while True:
                    line_bytes = f.readline()
                    if not line_bytes:
                        break
                    # If line does not end with newline, it is an incomplete tail line
                    if not line_bytes.endswith(b"\n"):
                        break
                    line_str = line_bytes.decode("utf-8", errors="replace").strip()
                    if line_str:
                        try:
                            event = OperationalEvent.model_validate(json.loads(line_str))
                            self._seen_event_ids.add(event.event_id)
                            if event.event_id not in loaded_ids:
                                loaded_ids.add(event.event_id)
                                self._events.append(event)
                        except Exception as exc:
                            logger.warning("Failed to parse event line: %s", exc)
                    self._file_offset = f.tell()

    def _load(self) -> None:
        with self._cross_process_lock(), self._lock:
            self._sync_locked()

    def _persist(self, event: OperationalEvent) -> None:
        with self._events_file.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")
            handle.flush()
            self._file_offset = handle.tell()
        tmp_index = self._store_path / f"event_ids.json.tmp.{os.getpid()}"
        tmp_index.write_text(
            json.dumps(sorted(self._seen_event_ids), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_index, self._index_file)

    async def append(self, event: OperationalEvent) -> bool:
        with self._cross_process_lock(), self._lock:
            self._sync_locked()
            if event.event_id in self._seen_event_ids:
                return False
            self._seen_event_ids.add(event.event_id)
            self._events.append(event)
            self._persist(event)
            return True

    async def purge_expired(self) -> int:
        with self._cross_process_lock(), self._lock:
            self._sync_locked()
            now = utc_now()
            remaining = []
            removed = 0
            for event in self._events:
                if event.retention_expires_at and event.retention_expires_at <= now:
                    removed += 1
                else:
                    remaining.append(event)
            if removed:
                self._events = remaining
                self._seen_event_ids = {e.event_id for e in remaining}
                tmp_events = self._store_path / f"events.jsonl.tmp.{os.getpid()}"
                with tmp_events.open("w", encoding="utf-8") as f:
                    for event in self._events:
                        f.write(event.model_dump_json() + "\n")
                os.replace(tmp_events, self._events_file)
                stat = self._events_file.stat()
                self._file_offset = stat.st_size
                self._file_inode = getattr(stat, "st_ino", None)

                tmp_index = self._store_path / f"event_ids.json.tmp.{os.getpid()}"
                tmp_index.write_text(
                    json.dumps(sorted(self._seen_event_ids), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                os.replace(tmp_index, self._index_file)
            return removed

