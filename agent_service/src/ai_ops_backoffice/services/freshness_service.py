from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime
from typing import Literal

from agent_service.operations.contracts import FreshnessMetadata, utc_now

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
    ) -> None:
        self._lock = threading.RLock()
        # Stale threshold must exceed the heartbeat interval or healthy workers look dead.
        self._heartbeat_interval = heartbeat_interval_seconds
        self._worker_stale_threshold = max(
            worker_stale_threshold_seconds, heartbeat_interval_seconds * 2
        )
        self._realtime_lag_threshold = realtime_lag_threshold_seconds
        self._last_worker_heartbeat: datetime | None = None
        self._is_worker_connected: bool = True
        self._last_successful_sync: dict[str, datetime] = {}
        # correlation_id -> stage -> timestamp
        self._stage_events: dict[str, dict[str, datetime]] = defaultdict(dict)

    def record_worker_heartbeat(self, worker_id: str = "worker-1", at: datetime | None = None) -> None:
        with self._lock:
            self._last_worker_heartbeat = at or utc_now()
            self._is_worker_connected = True

    def set_worker_disconnected(self) -> None:
        with self._lock:
            self._is_worker_connected = False

    def is_worker_active(self, now: datetime | None = None) -> bool:
        with self._lock:
            if not self._is_worker_connected:
                return False
            if self._last_worker_heartbeat is None:
                return False
            check_time = now or utc_now()
            elapsed = (check_time - self._last_worker_heartbeat).total_seconds()
            return elapsed <= self._worker_stale_threshold

    def record_stage_event(
        self,
        correlation_id: str,
        stage: StageName,
        at: datetime | None = None,
    ) -> None:
        """Records a timestamp for an event stage tagged by correlationId (A05-T1)."""
        with self._lock:
            self._stage_events[correlation_id][stage] = at or utc_now()

    def record_sync_success(self, resource_type: str, at: datetime | None = None) -> None:
        with self._lock:
            self._last_successful_sync[resource_type] = at or utc_now()

    def compute_freshness(
        self,
        resource_type: str = "conversations",
        watermark: datetime | None = None,
        is_syncing: bool = False,
        now: datetime | None = None,
    ) -> FreshnessMetadata:
        """Calculates FreshnessMetadata from ingest/aggregation completion, not raw event time.

        An empty event stream does not imply pipeline lag. Prefer the latest
        EVENT_INGESTED / AGGREGATION_COMPLETED stage or last successful sync.
        """
        now_dt = now or utc_now()
        with self._lock:
            worker_alive = self.is_worker_active(now_dt)
            last_sync = self._last_successful_sync.get(resource_type)
            if last_sync is None:
                norm_key = (resource_type or "").strip().lower()
                for alt in (norm_key.replace("_", "-"), norm_key.replace("-", "_")):
                    if alt in self._last_successful_sync:
                        last_sync = self._last_successful_sync[alt]
                        break
            pipeline_watermark = self._latest_pipeline_watermark(resource_type)
            # Explicit watermark wins for callers that already resolved pipeline time.
            # Otherwise prefer ingest/aggregation completion over raw event time.
            if watermark is not None:
                effective_watermark = watermark
            else:
                effective_watermark = pipeline_watermark or last_sync

            if not effective_watermark:
                return FreshnessMetadata(
                    event_watermark=None,
                    materialized_at=None,
                    served_at=now_dt,
                    lag_seconds=None,
                    status="UNKNOWN",
                    last_successful_sync_at=last_sync,
                )

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

    def _latest_pipeline_watermark(self, resource_type: str) -> datetime | None:
        norm = (resource_type or "").strip().lower()
        if norm == "conversations":
            preferred_stages = (
                "CONVERSATION_LIST_RENDERED",
                "EVENT_INGESTED",
            )
        elif norm in (
            "reporting",
            "daily_aggregates",
            "operations_summary",
            "operations-overview",
            "operations_overview",
        ):
            preferred_stages = (
                "AGGREGATION_COMPLETED",
            )
        elif norm in ("sources", "knowledge"):
            preferred_stages = (
                "SOURCE_SYNC_COMPLETED",
            )
        else:
            preferred_stages = (
                "AGGREGATION_COMPLETED",
                "EVENT_INGESTED",
                "SOURCE_SYNC_COMPLETED",
                "CONVERSATION_LIST_RENDERED",
            )

        latest: datetime | None = None
        # Check resource-keyed stage events first (supporting hyphen / underscore normalization)
        for key in (norm, norm.replace("_", "-"), norm.replace("-", "_")):
            if key in self._stage_events:
                for stage in preferred_stages:
                    stamp = self._stage_events[key].get(stage)
                    if stamp is not None and (latest is None or stamp > latest):
                        latest = stamp
        if latest is not None:
            return latest

        for stages in self._stage_events.values():
            for stage in preferred_stages:
                stamp = stages.get(stage)
                if stamp is None:
                    continue
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
