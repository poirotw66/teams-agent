"""Operations-level freshness recorder for cross-service observability.

Provides a robust, dependency-inverted implementation of FreshnessRecorder
that delegates state persistence to FreshnessStore, supporting atomic Firestore
transactions and multi-instance monotonic advancement.

This module resides in the core operations layer, eliminating any reverse
dependency from the operations runtime onto the backoffice presentation layer.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import FreshnessRecorder
from .freshness_store import FreshnessStore

logger = logging.getLogger(__name__)


class OperationsFreshnessRecorder(FreshnessRecorder):
    """Core operations-level freshness recorder supporting granular Firestore writes."""

    def __init__(
        self,
        *,
        persistent_path: Path | None = None,
        firestore_client: Any = None,
        firestore_collection: str = "freshness_state",
        clock: Any = None,
        max_stage_events: int = 5000,
        store: FreshnessStore | None = None,
    ) -> None:
        self._store = store or FreshnessStore(
            persistent_path=persistent_path,
            firestore_client=firestore_client,
            firestore_collection=firestore_collection,
            clock=clock,
            max_stage_events=max_stage_events,
        )
        self._lock = self._store._lock
        self._persistent_path = persistent_path
        self._firestore_client = firestore_client
        self._firestore_collection = firestore_collection
        self._clock = clock
        self._max_stage_events = max_stage_events

    @property
    def _last_successful_sync(self) -> dict[str, datetime]:
        return self._store._last_successful_sync

    @property
    def _worker_heartbeats(self) -> dict[str, datetime]:
        return self._store._worker_heartbeats

    @property
    def _stage_events(self) -> Any:
        return self._store._stage_events

    def now(self) -> datetime:
        return self._store.now()

    def record_stage_event(
        self,
        correlation_id: str,
        stage: str,
        at: datetime | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Records a timestamp for an event stage tagged by correlationId."""
        now_val = at or self.now()
        self._store.save_stage_event(correlation_id, stage, now_val, tenant_id=tenant_id)

    def record_sync_success(
        self,
        resource_type: str,
        at: datetime | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Records successful synchronization with cross-instance monotonic advancement."""
        key = f"{tenant_id}:{resource_type}" if tenant_id else resource_type
        now_val = at or self.now()
        self._store.save_watermark(key, now_val)

    def record_worker_heartbeat(
        self,
        worker_id: str = "worker-1",
        at: datetime | None = None,
    ) -> None:
        """Records a worker heartbeat with cross-instance monotonic advancement."""
        now_val = at or self.now()
        self._store.save_heartbeat(worker_id, now_val)

    def record_backlog(
        self,
        resource_type: str,
        backlog_count: int,
        oldest_pending_at: datetime | None = None,
        tenant_id: str | None = None,
        at: datetime | None = None,
    ) -> None:
        """Records backlog evidence for idle pipeline calculations."""
        key = f"{tenant_id}:{resource_type}" if tenant_id else resource_type
        now_val = at or self.now()
        self._store.save_backlog(key, backlog_count, oldest_pending_at, now_val)

    def _save_firestore_watermark(self, key: str, at: datetime) -> None:
        self._store._save_firestore_watermark(key, at)

    def _save_firestore_heartbeat(self, worker_id: str, at: datetime) -> None:
        self._store._save_firestore_heartbeat(worker_id, at)

    def _save_persistent_sync(self) -> None:
        self._store._save_persistent()

    def _load_persistent_sync(self) -> None:
        self._store.load_persistent()
