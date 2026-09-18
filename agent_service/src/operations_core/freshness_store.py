"""Unified persistence adapter for operational freshness metadata.

Provides atomic, monotonic state persistence across Firestore and local storage,
ensuring multi-instance concurrency safety via Firestore transactions and
eliminating race conditions during watermark/heartbeat advancements.

Write and query surfaces live in sibling modules; this module keeps the public
``FreshnessStore`` API stable for importers.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from operations_core.contracts import utc_now
from operations_core.freshness_store_queries import FreshnessStoreQueries
from operations_core.freshness_store_writes import FreshnessStoreWrites


class FreshnessStore(FreshnessStoreWrites, FreshnessStoreQueries):
    """Encapsulates durable and in-memory storage for freshness tracking."""

    def __init__(
        self,
        *,
        persistent_path: Path | None = None,
        firestore_client: Any = None,
        firestore_collection: str = "freshness_state",
        clock: Any = None,
        max_stage_events: int = 5000,
    ) -> None:
        self.lock = threading.RLock()
        self._persistent_path = persistent_path
        self._firestore_client = firestore_client
        self._firestore_collection = firestore_collection
        self._clock = clock
        self._max_stage_events = max_stage_events

        self.last_successful_sync: dict[str, datetime] = {}
        self.worker_heartbeats: dict[str, datetime] = {}
        self.pending_backlog: dict[str, dict[str, Any]] = {}
        self.stage_events: OrderedDict[str, dict[str, Any]] = OrderedDict()

        self.last_file_mtime: float = 0.0
        self.last_firestore_poll: float = 0.0

        if self._persistent_path and self._persistent_path.exists():
            self.load_persistent()
        if self._firestore_client is not None:
            self.load_firestore()

    def now(self) -> datetime:
        if self._clock is not None:
            return self._clock()
        return utc_now()


__all__ = ["FreshnessStore"]
