from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from ..contracts import OperationalEvent
from .journal import Lease, claim_record, expire_record, register, settle_record, summarize


class FileJournal:
    """SQLite FULL-synchronous journal on a persistent LOCAL development volume.

    None is explicitly volatile and exists only for MEMORY-mode tests. A local
    file on Cloud Run's ephemeral filesystem does not provide service durability.
    """

    def __init__(self, path: Path | None) -> None:
        self.durable = path is not None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self._lock = Lock()
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA secure_delete=ON")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS outbox (event_id TEXT PRIMARY KEY, body TEXT NOT NULL, "
            "wake_at REAL NOT NULL)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS outbox_due ON outbox(wake_at)")
        self._db.commit()

    def _transaction(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                result = operation(self._db)
                self._db.commit()
                return result
            except BaseException:
                self._db.rollback()
                raise

    @staticmethod
    def _save(db: sqlite3.Connection, event_id: str, record: dict[str, Any]) -> None:
        db.execute("INSERT OR REPLACE INTO outbox VALUES (?, ?, ?)", (
            event_id, json.dumps(record, allow_nan=False), record["wake_at"],
        ))

    async def put(self, event: OperationalEvent, sinks: list[str], now: float) -> bool:
        key = hashlib.sha256(event.event_id.encode()).hexdigest()
        def operation(db: sqlite3.Connection) -> bool:
            row = db.execute("SELECT body FROM outbox WHERE event_id=?", (key,)).fetchone()
            record, inserted = register(json.loads(row[0]) if row else None, event, sinks, now)
            self._save(db, key, record)
            return inserted
        return await asyncio.to_thread(self._transaction, operation)

    async def claim(
        self, targets: set[str], now: float, lease_seconds: float, limit: int,
        event_id: str | None = None,
    ) -> list[Lease]:
        def operation(db: sqlite3.Connection) -> list[Lease]:
            if event_id is None:
                rows = db.execute("SELECT event_id, body FROM outbox WHERE wake_at<=? "
                                  "ORDER BY wake_at, event_id", (now,)).fetchall()
            else:
                rows = db.execute("SELECT event_id, body FROM outbox WHERE event_id=?",
                                  (hashlib.sha256(event_id.encode()).hexdigest(),)).fetchall()
            leases: list[Lease] = []
            for key, body in rows:
                record = json.loads(body)
                claimed = claim_record(record, targets, now, lease_seconds, limit - len(leases))
                self._save(db, key, record)
                leases.extend(claimed)
                if len(leases) >= limit:
                    break
            return leases
        return await asyncio.to_thread(self._transaction, operation)

    async def settle(
        self, lease: Lease, now: float, error: str | None = None, delay: float = 0,
    ) -> bool:
        def operation(db: sqlite3.Connection) -> bool:
            key = hashlib.sha256(lease.event.event_id.encode()).hexdigest()
            row = db.execute("SELECT body FROM outbox WHERE event_id=?", (key,))
            record = json.loads(row.fetchone()[0])
            changed = settle_record(record, lease, now, error, delay)
            self._save(db, key, record)
            return changed
        return await asyncio.to_thread(self._transaction, operation)

    async def purge(self, now: float) -> int:
        def operation(db: sqlite3.Connection) -> int:
            changed = 0
            for key, body in db.execute("SELECT event_id, body FROM outbox").fetchall():
                record = json.loads(body)
                if expire_record(record, now):
                    self._save(db, key, record)
                    changed += 1
            return changed
        return await asyncio.to_thread(self._transaction, operation)

    async def stats(self, now: float) -> dict[str, Any]:
        return await asyncio.to_thread(self._transaction, lambda db: summarize([
            json.loads(row[0]) for row in db.execute("SELECT body FROM outbox")
        ], now))

    def close(self) -> None:
        with self._lock:
            self._db.close()
