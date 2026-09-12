"""Operations-level freshness recorder for cross-service observability.

Provides a robust, dependency-inverted implementation of FreshnessRecorder
that persists stage events, sync watermarks, and worker heartbeats to Firestore
and/or local storage with cross-instance monotonic advancement.

This module resides in the core operations layer, eliminating any reverse
dependency from the operations runtime onto the backoffice presentation layer.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import FreshnessRecorder, utc_now

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
    ) -> None:
        self._lock = threading.RLock()
        self._persistent_path = persistent_path
        self._firestore_client = firestore_client
        self._firestore_collection = firestore_collection
        self._clock = clock
        self._max_stage_events = max_stage_events
        self._last_successful_sync: dict[str, datetime] = {}
        self._worker_heartbeats: dict[str, datetime] = {}
        self._stage_events: OrderedDict[str, dict[str, Any]] = OrderedDict()

        if self._persistent_path and self._persistent_path.exists():
            self._load_persistent_sync()

    def now(self) -> datetime:
        if self._clock is not None:
            return self._clock()
        return utc_now()

    def record_stage_event(
        self,
        correlation_id: str,
        stage: str,
        at: datetime | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Records a timestamp for an event stage tagged by correlationId."""
        now_val = at or self.now()
        with self._lock:
            if (
                correlation_id not in self._stage_events
                and len(self._stage_events) >= self._max_stage_events
            ):
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
        """Records successful synchronization with cross-instance monotonic advancement."""
        key = f"{tenant_id}:{resource_type}" if tenant_id else resource_type
        now_val = at or self.now()
        with self._lock:
            existing = self._last_successful_sync.get(key)
            if existing is not None and now_val < existing:
                return  # In-memory monotonic check
            self._last_successful_sync[key] = now_val
            self._save_persistent_sync()
            self._save_firestore_watermark(key, now_val)

    def record_worker_heartbeat(
        self,
        worker_id: str = "worker-1",
        at: datetime | None = None,
    ) -> None:
        """Records a worker heartbeat with cross-instance monotonic advancement."""
        now_val = at or self.now()
        with self._lock:
            existing = self._worker_heartbeats.get(worker_id)
            if existing is not None and now_val < existing:
                return
            self._worker_heartbeats[worker_id] = now_val
            self._save_persistent_sync()
            self._save_firestore_heartbeat(worker_id, now_val)

    def _save_firestore_watermark(self, key: str, at: datetime) -> None:
        if self._firestore_client is None:
            return
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_id = f"wm_{key.replace(':', '_')}"
            ref_indiv = col.document(doc_id)

            # Cross-instance monotonic verification: read existing from Firestore first
            snap = ref_indiv.get() if hasattr(ref_indiv, "get") else None
            if snap and getattr(snap, "exists", False):
                existing_data = snap.to_dict() or {}
                existing_at_str = existing_data.get("at")
                if isinstance(existing_at_str, str):
                    try:
                        existing_at = datetime.fromisoformat(existing_at_str)
                        if at < existing_at:
                            with self._lock:
                                cur = self._last_successful_sync.get(key)
                                if cur is None or existing_at > cur:
                                    self._last_successful_sync[key] = existing_at
                            return
                    except Exception:
                        pass
            elif hasattr(ref_indiv, "coll") and hasattr(ref_indiv.coll, "store"):
                # Handle dictionary storage in tests
                stored_entry = ref_indiv.coll.store.get((ref_indiv.coll.name, ref_indiv.key), {})
                existing_at_str = stored_entry.get("at")
                if isinstance(existing_at_str, str):
                    try:
                        existing_at = datetime.fromisoformat(existing_at_str)
                        if at < existing_at:
                            with self._lock:
                                cur = self._last_successful_sync.get(key)
                                if cur is None or existing_at > cur:
                                    self._last_successful_sync[key] = existing_at
                            return
                    except Exception:
                        pass

            payload = {
                "key": key,
                "at": at.isoformat(),
                "updated_at": utc_now().isoformat(),
            }
            if hasattr(ref_indiv, "set"):
                ref_indiv.set(payload, merge=True)
            elif hasattr(ref_indiv, "coll") and hasattr(ref_indiv.coll, "store"):
                ref_indiv.coll.store.setdefault((ref_indiv.coll.name, ref_indiv.key), {}).update(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore sync watermark for %s: %s", key, exc)

    def _save_firestore_heartbeat(self, worker_id: str, at: datetime) -> None:
        if self._firestore_client is None:
            return
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_id = f"hb_{worker_id}"
            ref_indiv = col.document(doc_id)

            snap = ref_indiv.get() if hasattr(ref_indiv, "get") else None
            if snap and getattr(snap, "exists", False):
                existing_data = snap.to_dict() or {}
                existing_at_str = existing_data.get("at")
                if isinstance(existing_at_str, str):
                    try:
                        existing_at = datetime.fromisoformat(existing_at_str)
                        if at < existing_at:
                            with self._lock:
                                cur = self._worker_heartbeats.get(worker_id)
                                if cur is None or existing_at > cur:
                                    self._worker_heartbeats[worker_id] = existing_at
                            return
                    except Exception:
                        pass
            elif hasattr(ref_indiv, "coll") and hasattr(ref_indiv.coll, "store"):
                stored_entry = ref_indiv.coll.store.get((ref_indiv.coll.name, ref_indiv.key), {})
                existing_at_str = stored_entry.get("at")
                if isinstance(existing_at_str, str):
                    try:
                        existing_at = datetime.fromisoformat(existing_at_str)
                        if at < existing_at:
                            with self._lock:
                                cur = self._worker_heartbeats.get(worker_id)
                                if cur is None or existing_at > cur:
                                    self._worker_heartbeats[worker_id] = existing_at
                            return
                    except Exception:
                        pass

            payload = {
                "worker_id": worker_id,
                "at": at.isoformat(),
                "updated_at": utc_now().isoformat(),
            }
            if hasattr(ref_indiv, "set"):
                ref_indiv.set(payload, merge=True)
            elif hasattr(ref_indiv, "coll") and hasattr(ref_indiv.coll, "store"):
                ref_indiv.coll.store.setdefault((ref_indiv.coll.name, ref_indiv.key), {}).update(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore heartbeat for %s: %s", worker_id, exc)

    def _save_persistent_sync(self) -> None:
        try:
            if self._persistent_path:
                self._persistent_path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "watermarks": {k: v.isoformat() for k, v in self._last_successful_sync.items()},
                    "heartbeats": {k: v.isoformat() for k, v in self._worker_heartbeats.items()},
                    "updated_at": self.now().isoformat(),
                }
                self._persistent_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save persistent sync watermarks: %s", exc)

    def _load_persistent_sync(self) -> None:
        try:
            if self._persistent_path and self._persistent_path.exists():
                raw = self._persistent_path.read_text(encoding="utf-8").strip()
                if raw:
                    data = json.loads(raw)
                    wm_data = data.get("watermarks") if "watermarks" in data and isinstance(data["watermarks"], dict) else {}
                    for k, v in wm_data.items():
                        if isinstance(v, str):
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
                            except Exception:
                                pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load persistent sync watermarks: %s", exc)
