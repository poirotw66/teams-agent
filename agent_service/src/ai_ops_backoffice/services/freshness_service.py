from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

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
        max_stage_events: int = 5000,
        persistent_path: Path | None = None,
        clock: Any = None,
        firestore_client: Any = None,
        firestore_collection: str = "freshness_state",
    ) -> None:
        self._lock = threading.RLock()
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
        self._last_mtime: float = 0.0
        self._last_firestore_poll: float = 0.0
        self._last_worker_heartbeat: datetime | None = None
        self._is_worker_connected: bool = True
        self._worker_heartbeats: dict[str, datetime] = {}
        self._last_successful_sync: dict[str, datetime] = {}
        # correlation_id -> stage -> timestamp with bounded FIFO capacity
        self._stage_events: OrderedDict[str, dict[str, Any]] = OrderedDict()
        if self._persistent_path and self._persistent_path.exists():
            self._load_persistent_sync()
        if self._firestore_client is not None:
            self._load_firestore_sync()

    def now(self) -> datetime:
        return self._clock() if self._clock is not None else utc_now()

    def _load_persistent_sync(self) -> None:
        try:
            if self._persistent_path and self._persistent_path.exists():
                self._last_mtime = self._persistent_path.stat().st_mtime
                raw = self._persistent_path.read_text(encoding="utf-8")
                if not raw.strip():
                    return
                data = json.loads(raw)
                if isinstance(data, dict):
                    watermarks = data.get("watermarks") if "watermarks" in data and isinstance(data["watermarks"], dict) else data
                    for k, v in watermarks.items():
                        if isinstance(v, str) and k != "heartbeats":
                            try:
                                dt = datetime.fromisoformat(v)
                                existing = self._last_successful_sync.get(k)
                                if existing is None or dt > existing:
                                    self._last_successful_sync[k] = dt
                            except Exception:
                                pass
                    hb_data = data.get("heartbeats") if "heartbeats" in data and isinstance(data["heartbeats"], dict) else {}
                    for wid, ts_str in hb_data.items():
                        if isinstance(ts_str, str):
                            try:
                                hb_dt = datetime.fromisoformat(ts_str)
                                existing_hb = self._worker_heartbeats.get(wid)
                                if existing_hb is None or hb_dt > existing_hb:
                                    self._worker_heartbeats[wid] = hb_dt
                                    if self._last_worker_heartbeat is None or hb_dt > self._last_worker_heartbeat:
                                        self._last_worker_heartbeat = hb_dt
                            except Exception:
                                pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load persistent sync watermarks: %s", exc)

    def _load_firestore_sync(self) -> None:
        if self._firestore_client is None:
            return
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            wm_ref = col.document("watermarks")
            snap_wm = wm_ref.get() if hasattr(wm_ref, "get") else None
            if snap_wm and getattr(snap_wm, "exists", False):
                wm_data = snap_wm.to_dict() or {}
                for k, v in wm_data.items():
                    if isinstance(v, str):
                        try:
                            dt = datetime.fromisoformat(v)
                            existing = self._last_successful_sync.get(k)
                            if existing is None or dt > existing:
                                self._last_successful_sync[k] = dt
                        except Exception:
                            pass
            hb_ref = col.document("heartbeats")
            snap_hb = hb_ref.get() if hasattr(hb_ref, "get") else None
            if snap_hb and getattr(snap_hb, "exists", False):
                hb_data = snap_hb.to_dict() or {}
                for wid, ts_str in hb_data.items():
                    if isinstance(ts_str, str):
                        try:
                            hb_dt = datetime.fromisoformat(ts_str)
                            existing_hb = self._worker_heartbeats.get(wid)
                            if existing_hb is None or hb_dt > existing_hb:
                                self._worker_heartbeats[wid] = hb_dt
                                if self._last_worker_heartbeat is None or hb_dt > self._last_worker_heartbeat:
                                    self._last_worker_heartbeat = hb_dt
                        except Exception:
                            pass
            import time
            self._last_firestore_poll = time.time()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load Firestore sync watermarks: %s", exc)

    def _save_firestore_watermark(self, key: str, at: datetime) -> None:
        if self._firestore_client is None:
            return
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            # Granular document per tenant/resource to eliminate hotspot contention
            doc_id = f"wm_{key.replace(':', '_')}"
            ref_indiv = col.document(doc_id)
            payload = {"key": key, "at": at.isoformat()}
            if hasattr(ref_indiv, "set"):
                ref_indiv.set(payload, merge=True)
            elif hasattr(ref_indiv, "coll") and hasattr(ref_indiv.coll, "store"):
                ref_indiv.coll.store.setdefault((ref_indiv.coll.name, ref_indiv.key), {}).update(payload)

            # Aggregate document for batch queries and backward compatibility
            ref = col.document("watermarks")
            if hasattr(ref, "set"):
                ref.set({key: at.isoformat()}, merge=True)
            elif hasattr(ref, "coll") and hasattr(ref.coll, "store"):
                ref.coll.store.setdefault((ref.coll.name, ref.key), {})[key] = at.isoformat()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore sync watermark for %s: %s", key, exc)

    def _save_firestore_heartbeat(self, worker_id: str, at: datetime) -> None:
        if self._firestore_client is None:
            return
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            # Granular document per worker to eliminate hotspot contention
            doc_id = f"hb_{worker_id}"
            ref_indiv = col.document(doc_id)
            payload = {"worker_id": worker_id, "at": at.isoformat()}
            if hasattr(ref_indiv, "set"):
                ref_indiv.set(payload, merge=True)
            elif hasattr(ref_indiv, "coll") and hasattr(ref_indiv.coll, "store"):
                ref_indiv.coll.store.setdefault((ref_indiv.coll.name, ref_indiv.key), {}).update(payload)

            # Aggregate document for batch queries and backward compatibility
            ref = col.document("heartbeats")
            if hasattr(ref, "set"):
                ref.set({worker_id: at.isoformat()}, merge=True)
            elif hasattr(ref, "coll") and hasattr(ref.coll, "store"):
                ref.coll.store.setdefault((ref.coll.name, ref.key), {})[worker_id] = at.isoformat()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore heartbeat for %s: %s", worker_id, exc)

    def _reload_persistent_sync_if_needed(self) -> None:
        if self._persistent_path and self._persistent_path.exists():
            try:
                mtime = self._persistent_path.stat().st_mtime
                if mtime > self._last_mtime:
                    self._load_persistent_sync()
            except Exception:
                pass
        if self._firestore_client is not None:
            import time
            now_ts = time.time()
            if now_ts - self._last_firestore_poll > 2.0:
                self._load_firestore_sync()

    def _save_persistent_sync(self) -> None:
        try:
            if self._persistent_path:
                self._persistent_path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "watermarks": {k: v.isoformat() for k, v in self._last_successful_sync.items()},
                    "heartbeats": {k: v.isoformat() for k, v in self._worker_heartbeats.items()},
                }
                tmp = self._persistent_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                tmp.replace(self._persistent_path)
                self._last_mtime = self._persistent_path.stat().st_mtime
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save persistent sync watermarks: %s", exc)

    def record_worker_heartbeat(self, worker_id: str = "worker-1", at: datetime | None = None) -> None:
        now_val = at or self.now()
        with self._lock:
            existing = self._worker_heartbeats.get(worker_id)
            if existing is not None and now_val < existing:
                return  # Monotonic advance: never rewind
            self._last_worker_heartbeat = (
                max(self._last_worker_heartbeat, now_val)
                if self._last_worker_heartbeat is not None
                else now_val
            )
            self._is_worker_connected = True
            self._worker_heartbeats[worker_id] = now_val
            self._save_persistent_sync()
            self._save_firestore_heartbeat(worker_id, now_val)

    def set_worker_disconnected(self) -> None:
        with self._lock:
            self._is_worker_connected = False

    def is_worker_active(self, now: datetime | None = None) -> bool:
        self._reload_persistent_sync_if_needed()
        with self._lock:
            if not self._is_worker_connected:
                return False
            if self._last_worker_heartbeat is None:
                return False
            check_time = now or self.now()
            elapsed = (check_time - self._last_worker_heartbeat).total_seconds()
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
        with self._lock:
            if correlation_id not in self._stage_events and len(self._stage_events) >= self._max_stage_events:
                self._stage_events.popitem(last=False)
            entry = self._stage_events.setdefault(correlation_id, {})
            entry[stage] = now_val
            if tenant_id:
                entry["_tenant_id"] = tenant_id

    def record_sync_success(
        self,
        resource_type: str,
        at: datetime | None = None,
        tenant_id: str | None = None,
    ) -> None:
        key = f"{tenant_id}:{resource_type}" if tenant_id else resource_type
        now_val = at or self.now()
        with self._lock:
            existing = self._last_successful_sync.get(key)
            if existing is not None and now_val < existing:
                return  # Monotonic advance: never rewind
            self._last_successful_sync[key] = now_val
            # Strictly tenant-isolated: do not update global key when tenant_id is provided
            self._save_persistent_sync()
            self._save_firestore_watermark(key, now_val)

    def compute_freshness(
        self,
        resource_type: str = "conversations",
        watermark: datetime | None = None,
        is_syncing: bool = False,
        now: datetime | None = None,
        tenant_id: str | None = None,
    ) -> FreshnessMetadata:
        """Calculates FreshnessMetadata from ingest/aggregation completion, not raw event time.

        An empty event stream does not imply pipeline lag. Prefer the latest
        EVENT_INGESTED / AGGREGATION_COMPLETED stage or last successful sync.
        UI render time (CONVERSATION_LIST_RENDERED) is never used as sync evidence.
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
