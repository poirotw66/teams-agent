from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from agent_service.operations.contracts import FreshnessMetadata
from agent_service.operations.freshness_store import FreshnessStore

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
        self._lock = self._store._lock
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
        return self._store._last_file_mtime

    @_last_mtime.setter
    def _last_mtime(self, val: float) -> None:
        self._store._last_file_mtime = val

    @property
    def _last_firestore_poll(self) -> float:
        return self._store._last_firestore_poll

    @_last_firestore_poll.setter
    def _last_firestore_poll(self, val: float) -> None:
        self._store._last_firestore_poll = val

    @property
    def _worker_heartbeats(self) -> dict[str, datetime]:
        return self._store._worker_heartbeats

    @property
    def _last_successful_sync(self) -> dict[str, datetime]:
        return self._store._last_successful_sync

    @property
    def _pending_backlog(self) -> dict[str, dict[str, Any]]:
        return self._store._pending_backlog

    @property
    def _stage_events(self) -> OrderedDict[str, dict[str, Any]]:
        return self._store._stage_events

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
        self._store._save_firestore_watermark(key, at)

    def _save_firestore_heartbeat(self, worker_id: str, at: datetime) -> None:
        self._store._save_firestore_heartbeat(worker_id, at)

    def _reload_persistent_sync_if_needed(self) -> None:
        self._store.reload_if_needed()

    def _save_persistent_sync(self) -> None:
        self._store._save_persistent()

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
        """Calculates FreshnessMetadata from ingest/aggregation completion, not raw event time.

        An empty event stream does not imply pipeline lag. Prefer the latest
        EVENT_INGESTED / AGGREGATION_COMPLETED stage or last successful sync.
        UI render time (CONVERSATION_LIST_RENDERED) is never used as sync evidence.

        Idle Pipeline Handling:
        When the pipeline is healthy (worker alive), has synchronization evidence,
        and has recent verified backlog evidence of 0 (idle), it returns REALTIME
        with lag_seconds=0.0, while preserving the historical event_watermark.
        """
        self._reload_persistent_sync_if_needed()
        now_dt = now or self.now()
        with self._lock:
            worker_alive = self.is_worker_active(now_dt)
            if tenant_id:
                lookup_key = f"{tenant_id}:{resource_type}"
                last_sync = self._last_successful_sync.get(lookup_key)
            else:
                lookup_key = resource_type
                last_sync = self._last_successful_sync.get(lookup_key)
                if last_sync is None:
                    norm_key = (resource_type or "").strip().lower()
                    for alt in (norm_key.replace("_", "-"), norm_key.replace("-", "_")):
                        if alt in self._last_successful_sync:
                            last_sync = self._last_successful_sync[alt]
                            break

            pipeline_watermark = self._latest_pipeline_watermark(resource_type, tenant_id=tenant_id)

            # Explicit watermark wins for callers that already resolved pipeline time.
            # Otherwise prefer ingest/aggregation completion or last_sync.
            # UI render time (CONVERSATION_LIST_RENDERED) is presentation-only and must NEVER
            # serve as a pipeline watermark to claim REALTIME without sync/ingest evidence!
            if watermark is not None:
                effective_watermark = watermark
            elif pipeline_watermark is not None:
                effective_watermark = pipeline_watermark
            elif last_sync is not None:
                effective_watermark = last_sync
            else:
                effective_watermark = None

            if not effective_watermark:
                return FreshnessMetadata(
                    event_watermark=None,
                    materialized_at=None,
                    served_at=now_dt,
                    lag_seconds=None,
                    status="UNKNOWN",
                    last_successful_sync_at=last_sync,
                )

            # Resolve backlog state and freshness
            stored_backlog = self._pending_backlog.get(lookup_key)
            if stored_backlog is None and not tenant_id:
                stored_backlog = self._pending_backlog.get(resource_type)

            effective_backlog_count = backlog_count
            effective_oldest_pending = None
            backlog_is_fresh = False

            if stored_backlog is not None:
                rec_at = stored_backlog.get("recorded_at")
                if rec_at is not None:
                    elapsed = (now_dt - rec_at).total_seconds()
                    if elapsed <= self._worker_stale_threshold:
                        backlog_is_fresh = True
                else:
                    backlog_is_fresh = worker_alive

                if effective_backlog_count is None and backlog_is_fresh:
                    effective_backlog_count = stored_backlog.get("count", 0)
                if backlog_is_fresh:
                    effective_oldest_pending = stored_backlog.get("oldest_pending_at")

            effective_has_backlog = has_pending_backlog
            if effective_has_backlog is None:
                if effective_backlog_count is not None:
                    effective_has_backlog = effective_backlog_count > 0
                elif is_idle is True:
                    effective_has_backlog = False

            # Determine pipeline lag vs raw event age
            # If idle pipeline (explicit is_idle=True, OR explicit has_pending_backlog=False,
            # OR recent observed backlog evidence exists and count is 0):
            # lag represents processing backlog delay (0.0), preserving event_watermark.
            if is_idle is True or effective_has_backlog is False or (effective_backlog_count == 0 and backlog_is_fresh and effective_has_backlog is not True):
                lag_seconds = 0.0
            elif effective_has_backlog is True and effective_oldest_pending is not None:
                lag_seconds = max(0.0, (now_dt - effective_oldest_pending).total_seconds())
            elif backlog_lag_seconds is not None:
                lag_seconds = max(0.0, backlog_lag_seconds)
            else:
                lag_seconds = max(0.0, (now_dt - effective_watermark).total_seconds())

            if not worker_alive:
                status: Literal["REALTIME", "SYNCING", "DELAYED", "FAILED", "UNKNOWN"] = (
                    "FAILED" if not self._is_worker_connected else "DELAYED"
                )
            elif is_syncing:
                status = "SYNCING"
            elif lag_seconds > self._realtime_lag_threshold:
                status = "DELAYED"
            else:
                status = "REALTIME"

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

    def _latest_pipeline_watermark(self, resource_type: str, tenant_id: str | None = None) -> datetime | None:
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

    def _latest_ui_render_watermark(self, resource_type: str, tenant_id: str | None = None) -> datetime | None:
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
        keys_to_check = [f"{tenant_id}:{norm}"] if tenant_id else [norm, norm.replace("_", "-"), norm.replace("-", "_")]
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
