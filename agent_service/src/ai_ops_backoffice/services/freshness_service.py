from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from operations_core.contracts import FreshnessMetadata
from operations_core.freshness_store import FreshnessStore

from .freshness_compute import (
    compute_lag_seconds,
    resolve_backlog_state,
    resolve_effective_watermark,
    resolve_freshness_status,
    resolve_last_sync,
)

logger = logging.getLogger(__name__)

StageName = Literal[
    "EVENT_OCCURRED",
    "EVENT_INGESTED",
    "CONVERSATION_LIST_RENDERED",
    "AGGREGATION_COMPLETED",
    "SOURCE_SYNC_COMPLETED",
    "SCHEDULE_DUE",
    "SCHEDULE_DISPATCHED",
]


class FreshnessTracker:
    """Manages operational data freshness metadata and SLA latency tracking across stages (Spec 7.3, A05-T1)."""

    def __init__(
        self,
        worker_stale_threshold_seconds: float = 600.0,
        realtime_lag_threshold_seconds: float = 60.0,
        heartbeat_interval_seconds: float = 300.0,
        max_stage_events: int = 5000,
        persistent_path: Path | None = None,
        clock: Any = None,
        firestore_client: Any = None,
        firestore_collection: str = "freshness_state",
        store: FreshnessStore | None = None,
    ) -> None:
        self._store = store or FreshnessStore(
            persistent_path=persistent_path,
            firestore_client=firestore_client,
            firestore_collection=firestore_collection,
            clock=clock,
            max_stage_events=max_stage_events,
        )
        self._lock = self._store.lock
        # Stale threshold must exceed the heartbeat interval or healthy workers look dead.
        self._heartbeat_interval = heartbeat_interval_seconds
        self._worker_stale_threshold = max(
            worker_stale_threshold_seconds, heartbeat_interval_seconds * 2
        )
        self._realtime_lag_threshold = realtime_lag_threshold_seconds
        self._max_stage_events = max_stage_events
        self._persistent_path = persistent_path
        self._firestore_client = firestore_client
        self._firestore_collection = firestore_collection
        self._clock = clock
        self._is_worker_connected: bool = True

    @property
    def _last_mtime(self) -> float:
        return self._store.last_file_mtime

    @_last_mtime.setter
    def _last_mtime(self, val: float) -> None:
        self._store.last_file_mtime = val

    @property
    def _last_firestore_poll(self) -> float:
        return self._store.last_firestore_poll

    @_last_firestore_poll.setter
    def _last_firestore_poll(self, val: float) -> None:
        self._store.last_firestore_poll = val

    @property
    def _worker_heartbeats(self) -> dict[str, datetime]:
        return self._store.worker_heartbeats

    @property
    def _last_successful_sync(self) -> dict[str, datetime]:
        return self._store.last_successful_sync

    @property
    def _pending_backlog(self) -> dict[str, dict[str, Any]]:
        return self._store.pending_backlog

    @property
    def _stage_events(self) -> OrderedDict[str, dict[str, Any]]:
        return self._store.stage_events

    @property
    def _last_worker_heartbeat(self) -> datetime | None:
        return self._store.get_latest_heartbeat()

    @_last_worker_heartbeat.setter
    def _last_worker_heartbeat(self, val: datetime | None) -> None:
        if val is not None:
            self._store.save_heartbeat("worker-1", val)

    def now(self) -> datetime:
        return self._store.now()

    def _load_persistent_sync(self) -> None:
        self._store.load_persistent()

    def _load_firestore_sync(self) -> None:
        self._store.load_firestore()

    def _save_firestore_watermark(self, key: str, at: datetime) -> None:
        self._store.save_firestore_watermark(key, at)

    def _save_firestore_heartbeat(self, worker_id: str, at: datetime) -> None:
        self._store.save_firestore_heartbeat(worker_id, at)

    def _reload_persistent_sync_if_needed(self) -> None:
        self._store.reload_if_needed()

    def _save_persistent_sync(self) -> None:
        self._store.save_persistent()

    def record_worker_heartbeat(
        self,
        worker_id: str = "worker-1",
        at: datetime | None = None,
    ) -> None:
        now_val = at or self.now()
        with self._lock:
            self._is_worker_connected = True
            self._store.save_heartbeat(worker_id, now_val)

    def record_backlog(
        self,
        resource_type: str,
        backlog_count: int,
        oldest_pending_at: datetime | None = None,
        tenant_id: str | None = None,
        at: datetime | None = None,
    ) -> None:
        """Records pending backlog count and oldest unprocessed item timestamp (Spec 7.3, A05-T1)."""
        key = f"{tenant_id}:{resource_type}" if tenant_id else resource_type
        now_val = at or self.now()
        self._store.save_backlog(key, backlog_count, oldest_pending_at, now_val)

    def _save_firestore_backlog(
        self,
        key: str,
        count: int,
        oldest_pending_at: datetime | None,
    ) -> None:
        self._store.save_backlog(key, count, oldest_pending_at, self.now())

    def set_worker_disconnected(self) -> None:
        with self._lock:
            self._is_worker_connected = False

    def is_worker_active(self, now: datetime | None = None) -> bool:
        self._reload_persistent_sync_if_needed()
        with self._lock:
            if not self._is_worker_connected:
                return False
            latest_hb = self._store.get_latest_heartbeat()
            if latest_hb is None:
                return False
            check_time = now or self.now()
            elapsed = (check_time - latest_hb).total_seconds()
            return elapsed <= self._worker_stale_threshold

    def record_stage_event(
        self,
        correlation_id: str,
        stage: StageName,
        at: datetime | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Records a timestamp for an event stage tagged by correlationId (A05-T1)."""
        now_val = at or self.now()
        self._store.save_stage_event(correlation_id, stage, now_val, tenant_id=tenant_id)

    def record_sync_success(
        self,
        resource_type: str,
        at: datetime | None = None,
        tenant_id: str | None = None,
    ) -> None:
        key = f"{tenant_id}:{resource_type}" if tenant_id else resource_type
        now_val = at or self.now()
        self._store.save_watermark(key, now_val)

    def compute_freshness(
        self,
        resource_type: str = "conversations",
        watermark: datetime | None = None,
        is_syncing: bool = False,
        now: datetime | None = None,
        tenant_id: str | None = None,
        has_pending_backlog: bool | None = None,
        backlog_count: int | None = None,
        backlog_lag_seconds: float | None = None,
        is_idle: bool | None = None,
    ) -> FreshnessMetadata:
        """Build FreshnessMetadata from ingest/aggregation evidence, not raw event age."""
        self._reload_persistent_sync_if_needed()
        now_dt = now or self.now()
        with self._lock:
            return self._compute_freshness_locked(
                resource_type=resource_type,
                watermark=watermark,
                is_syncing=is_syncing,
                now_dt=now_dt,
                tenant_id=tenant_id,
                has_pending_backlog=has_pending_backlog,
                backlog_count=backlog_count,
                backlog_lag_seconds=backlog_lag_seconds,
                is_idle=is_idle,
            )

    def _compute_freshness_locked(
        self,
        *,
        resource_type: str,
        watermark: datetime | None,
        is_syncing: bool,
        now_dt: datetime,
        tenant_id: str | None,
        has_pending_backlog: bool | None,
        backlog_count: int | None,
        backlog_lag_seconds: float | None,
        is_idle: bool | None,
    ) -> FreshnessMetadata:
        worker_alive = self.is_worker_active(now_dt)
        lookup_key, last_sync = resolve_last_sync(
            self._store,
            resource_type=resource_type,
            tenant_id=tenant_id,
            firestore_client=self._firestore_client,
            last_successful_sync=self._last_successful_sync,
        )
        pipeline_watermark = self._latest_pipeline_watermark(resource_type, tenant_id=tenant_id)
        # Explicit watermark wins; UI render time must never claim REALTIME alone.
        effective_watermark = resolve_effective_watermark(
            watermark=watermark,
            pipeline_watermark=pipeline_watermark,
            last_sync=last_sync,
        )
        if not effective_watermark:
            return FreshnessMetadata(
                event_watermark=None,
                materialized_at=None,
                served_at=now_dt,
                lag_seconds=None,
                status="UNKNOWN",
                last_successful_sync_at=last_sync,
            )

        backlog = resolve_backlog_state(
            self._store,
            lookup_key=lookup_key,
            resource_type=resource_type,
            tenant_id=tenant_id,
            firestore_client=self._firestore_client,
            now_dt=now_dt,
            worker_alive=worker_alive,
            worker_stale_threshold=self._worker_stale_threshold,
            has_pending_backlog=has_pending_backlog,
            backlog_count=backlog_count,
            is_idle=is_idle,
        )
        lag_seconds = compute_lag_seconds(
            now_dt=now_dt,
            effective_watermark=effective_watermark,
            backlog=backlog,
            is_idle=is_idle,
            backlog_lag_seconds=backlog_lag_seconds,
        )
        status = resolve_freshness_status(
            worker_alive=worker_alive,
            is_worker_connected=self._is_worker_connected,
            is_syncing=is_syncing,
            lag_seconds=lag_seconds,
            realtime_lag_threshold=self._realtime_lag_threshold,
        )
        return FreshnessMetadata(
            event_watermark=effective_watermark,
            materialized_at=(
                effective_watermark
                if watermark is not None
                else (pipeline_watermark or last_sync or effective_watermark)
            ),
            served_at=now_dt,
            lag_seconds=round(lag_seconds, 2),
            status=status,
            last_successful_sync_at=last_sync,
        )

    def _latest_pipeline_watermark(
        self, resource_type: str, tenant_id: str | None = None
    ) -> datetime | None:
        norm = (resource_type or "").strip().lower()
        if norm == "conversations":
            primary_stages: tuple[StageName, ...] = ("EVENT_INGESTED",)
        elif norm in (
            "reporting",
            "daily_aggregates",
            "operations_summary",
            "operations-overview",
            "operations_overview",
        ):
            primary_stages = ("AGGREGATION_COMPLETED",)
        elif norm in ("sources", "knowledge"):
            primary_stages = ("SOURCE_SYNC_COMPLETED",)
        else:
            primary_stages = (
                "AGGREGATION_COMPLETED",
                "EVENT_INGESTED",
                "SOURCE_SYNC_COMPLETED",
            )
        return self._scan_stages(norm, primary_stages, tenant_id=tenant_id)

    def _latest_ui_render_watermark(
        self, resource_type: str, tenant_id: str | None = None
    ) -> datetime | None:
        norm = (resource_type or "").strip().lower()
        return self._scan_stages(norm, ("CONVERSATION_LIST_RENDERED",), tenant_id=tenant_id)

    def _scan_stages(
        self,
        norm: str,
        stages: tuple[StageName, ...],
        tenant_id: str | None = None,
    ) -> datetime | None:
        if not stages:
            return None
        latest: datetime | None = None
        keys_to_check = (
            [f"{tenant_id}:{norm}"]
            if tenant_id
            else [norm, norm.replace("_", "-"), norm.replace("-", "_")]
        )
        for key in keys_to_check:
            if key in self._stage_events:
                for stage in stages:
                    stamp = self._stage_events[key].get(stage)
                    if isinstance(stamp, datetime) and (latest is None or stamp > latest):
                        latest = stamp
        if latest is not None:
            return latest

        for st in self._stage_events.values():
            if tenant_id is not None and st.get("_tenant_id") != tenant_id:
                continue
            for stage in stages:
                stamp = st.get(stage)
                if isinstance(stamp, datetime):
                    if latest is None or stamp > latest:
                        latest = stamp
        return latest

    def calculate_p95_latency(
        self,
        start_stage: StageName,
        end_stage: StageName,
    ) -> float | None:
        """Computes p95 latency in seconds between two stages across all correlation traces (A05-T1)."""
        with self._lock:
            durations: list[float] = []
            for stages in self._stage_events.values():
                if start_stage in stages and end_stage in stages:
                    duration = (stages[end_stage] - stages[start_stage]).total_seconds()
                    if duration >= 0:
                        durations.append(duration)

            if not durations:
                return None
            if len(durations) == 1:
                return round(durations[0], 3)

            durations.sort()
            # Calculate 95th percentile
            k = round(0.95 * (len(durations) - 1))
            return round(durations[k], 3)
