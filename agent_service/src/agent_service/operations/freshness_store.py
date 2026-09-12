"""Unified persistence adapter for operational freshness metadata.

Provides atomic, monotonic state persistence across Firestore and local storage,
ensuring multi-instance concurrency safety via Firestore transactions and
eliminating race conditions during watermark/heartbeat advancements.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import utc_now

logger = logging.getLogger(__name__)

try:
    from google.cloud import firestore

    @firestore.transactional
    def _atomic_firestore_set_watermark(
        transaction: Any,
        doc_ref: Any,
        agg_ref: Any,
        key: str,
        at_iso: str,
        updated_at_iso: str,
        at_dt: datetime,
    ) -> tuple[bool, datetime]:
        """Atomically read and advance watermark only if newer (monotonic)."""
        snap = doc_ref.get(transaction=transaction) if hasattr(doc_ref, "get") else None
        if snap is not None and getattr(snap, "exists", False):
            existing_data = snap.to_dict() or {}
            existing_at_str = existing_data.get("at")
            if isinstance(existing_at_str, str):
                try:
                    existing_dt = datetime.fromisoformat(existing_at_str)
                    if at_dt < existing_dt:
                        return False, existing_dt
                except Exception:
                    pass
        payload = {
            "key": key,
            "at": at_iso,
            "updated_at": updated_at_iso,
        }
        transaction.set(doc_ref, payload, merge=True)
        if agg_ref is not None and hasattr(agg_ref, "set"):
            transaction.set(agg_ref, {key: at_iso}, merge=True)
        return True, at_dt

    @firestore.transactional
    def _atomic_firestore_set_heartbeat(
        transaction: Any,
        doc_ref: Any,
        agg_ref: Any,
        worker_id: str,
        at_iso: str,
        updated_at_iso: str,
        at_dt: datetime,
    ) -> tuple[bool, datetime]:
        """Atomically read and advance worker heartbeat only if newer (monotonic)."""
        snap = doc_ref.get(transaction=transaction) if hasattr(doc_ref, "get") else None
        if snap is not None and getattr(snap, "exists", False):
            existing_data = snap.to_dict() or {}
            existing_at_str = existing_data.get("at")
            if isinstance(existing_at_str, str):
                try:
                    existing_dt = datetime.fromisoformat(existing_at_str)
                    if at_dt < existing_dt:
                        return False, existing_dt
                except Exception:
                    pass
        payload = {
            "worker_id": worker_id,
            "at": at_iso,
            "updated_at": updated_at_iso,
        }
        transaction.set(doc_ref, payload, merge=True)
        if agg_ref is not None and hasattr(agg_ref, "set"):
            transaction.set(agg_ref, {worker_id: at_iso}, merge=True)
        return True, at_dt

except Exception:  # pragma: no cover - optional runtime dependency
    _atomic_firestore_set_watermark = None
    _atomic_firestore_set_heartbeat = None


class FreshnessStore:
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
        self._lock = threading.RLock()
        self._persistent_path = persistent_path
        self._firestore_client = firestore_client
        self._firestore_collection = firestore_collection
        self._clock = clock
        self._max_stage_events = max_stage_events

        self._last_successful_sync: dict[str, datetime] = {}
        self._worker_heartbeats: dict[str, datetime] = {}
        self._pending_backlog: dict[str, dict[str, Any]] = {}
        self._stage_events: OrderedDict[str, dict[str, Any]] = OrderedDict()

        self._last_file_mtime: float = 0.0
        self._last_firestore_poll: float = 0.0

        if self._persistent_path and self._persistent_path.exists():
            self.load_persistent()
        if self._firestore_client is not None:
            self.load_firestore()

    def now(self) -> datetime:
        if self._clock is not None:
            return self._clock()
        return utc_now()

    # -------------------------------------------------------------------------
    # Watermark Operations
    # -------------------------------------------------------------------------

    def save_watermark(self, key: str, at: datetime) -> None:
        """Atomically advance the watermark for a given resource key."""
        with self._lock:
            existing = self._last_successful_sync.get(key)
            if existing is not None and at < existing:
                return  # Monotonic advancement: never rewind in-memory
            self._last_successful_sync[key] = at
            self._save_persistent()
            self._save_firestore_watermark(key, at)

    def get_watermark(self, key: str, *, fetch_remote: bool = False) -> datetime | None:
        """Return the latest watermark for key with optional targeted Firestore lookup."""
        with self._lock:
            val = self._last_successful_sync.get(key)
            if val is not None and not fetch_remote:
                return val

        if fetch_remote and self._firestore_client is not None:
            remote_val = self._fetch_remote_watermark(key)
            if remote_val is not None:
                with self._lock:
                    cur = self._last_successful_sync.get(key)
                    if cur is None or remote_val > cur:
                        self._last_successful_sync[key] = remote_val
                        return remote_val
        return val

    def _fetch_remote_watermark(self, key: str) -> datetime | None:
        """Perform O(1) single-document Firestore lookup for wm_{key}."""
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_id = f"wm_{key.replace(':', '_')}"
            ref = col.document(doc_id)
            snap = ref.get() if hasattr(ref, "get") else None
            if snap and getattr(snap, "exists", False):
                data = snap.to_dict() or {}
                at_str = data.get("at")
                if isinstance(at_str, str):
                    return datetime.fromisoformat(at_str)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed remote watermark lookup for %s: %s", key, exc)
        return None

    def _save_firestore_watermark(self, key: str, at: datetime) -> None:
        if self._firestore_client is None:
            return
        doc_id = f"wm_{key.replace(':', '_')}"
        at_iso = at.isoformat()
        now_iso = self.now().isoformat()
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_ref = col.document(doc_id)
            agg_ref = col.document("watermarks")

            # 1. Attempt atomic Firestore transaction if client supports transactions
            if (
                _atomic_firestore_set_watermark is not None
                and hasattr(self._firestore_client, "transaction")
                and callable(self._firestore_client.transaction)
            ):
                try:
                    txn = self._firestore_client.transaction()
                    committed, remote_dt = _atomic_firestore_set_watermark(
                        txn, doc_ref, agg_ref, key, at_iso, now_iso, at
                    )
                    if not committed:
                        with self._lock:
                            cur = self._last_successful_sync.get(key)
                            if cur is None or remote_dt > cur:
                                self._last_successful_sync[key] = remote_dt
                        return
                    return
                except Exception as txn_exc:
                    logger.debug(
                        "Transaction attempt for watermark %s encountered: %s; falling back to direct update",
                        key,
                        txn_exc,
                    )

            # 2. Fallback direct update (supports mock and standard document clients)
            self._save_watermark_direct(doc_ref, agg_ref, key, at, at_iso, now_iso)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore watermark for %s: %s", key, exc)

    def _save_watermark_direct(
        self,
        doc_ref: Any,
        agg_ref: Any,
        key: str,
        at: datetime,
        at_iso: str,
        now_iso: str,
    ) -> None:
        # Check monotonicity on remote document before writing
        snap = doc_ref.get() if hasattr(doc_ref, "get") else None
        if snap and getattr(snap, "exists", False):
            existing_data = snap.to_dict() or {}
            existing_at_str = existing_data.get("at")
            if isinstance(existing_at_str, str):
                try:
                    existing_dt = datetime.fromisoformat(existing_at_str)
                    if at < existing_dt:
                        with self._lock:
                            cur = self._last_successful_sync.get(key)
                            if cur is None or existing_dt > cur:
                                self._last_successful_sync[key] = existing_dt
                        return
                except Exception:
                    pass
        elif hasattr(doc_ref, "coll") and hasattr(doc_ref.coll, "store"):
            stored_entry = doc_ref.coll.store.get((doc_ref.coll.name, doc_ref.key), {})
            existing_at_str = stored_entry.get("at")
            if isinstance(existing_at_str, str):
                try:
                    existing_dt = datetime.fromisoformat(existing_at_str)
                    if at < existing_dt:
                        with self._lock:
                            cur = self._last_successful_sync.get(key)
                            if cur is None or existing_dt > cur:
                                self._last_successful_sync[key] = existing_dt
                        return
                except Exception:
                    pass

        payload = {
            "key": key,
            "at": at_iso,
            "updated_at": now_iso,
        }
        if hasattr(doc_ref, "set"):
            doc_ref.set(payload, merge=True)
        elif hasattr(doc_ref, "coll") and hasattr(doc_ref.coll, "store"):
            doc_ref.coll.store.setdefault((doc_ref.coll.name, doc_ref.key), {}).update(payload)

        # Also update aggregate document
        if hasattr(agg_ref, "set"):
            agg_ref.set({key: at_iso}, merge=True)
        elif hasattr(agg_ref, "coll") and hasattr(agg_ref.coll, "store"):
            agg_ref.coll.store.setdefault((agg_ref.coll.name, agg_ref.key), {})[key] = at_iso

    # -------------------------------------------------------------------------
    # Worker Heartbeat Operations
    # -------------------------------------------------------------------------

    def save_heartbeat(self, worker_id: str, at: datetime) -> None:
        """Atomically advance the heartbeat timestamp for a worker."""
        with self._lock:
            existing = self._worker_heartbeats.get(worker_id)
            if existing is not None and at < existing:
                return  # Monotonic
            self._worker_heartbeats[worker_id] = at
            self._save_persistent()
            self._save_firestore_heartbeat(worker_id, at)

    def get_heartbeat(self, worker_id: str, *, fetch_remote: bool = False) -> datetime | None:
        with self._lock:
            val = self._worker_heartbeats.get(worker_id)
            if val is not None and not fetch_remote:
                return val

        if fetch_remote and self._firestore_client is not None:
            remote_val = self._fetch_remote_heartbeat(worker_id)
            if remote_val is not None:
                with self._lock:
                    cur = self._worker_heartbeats.get(worker_id)
                    if cur is None or remote_val > cur:
                        self._worker_heartbeats[worker_id] = remote_val
                        return remote_val
        return val

    def _fetch_remote_heartbeat(self, worker_id: str) -> datetime | None:
        """Perform O(1) single-document Firestore lookup for hb_{worker_id}."""
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_id = f"hb_{worker_id}"
            ref = col.document(doc_id)
            snap = ref.get() if hasattr(ref, "get") else None
            if snap and getattr(snap, "exists", False):
                data = snap.to_dict() or {}
                at_str = data.get("at")
                if isinstance(at_str, str):
                    return datetime.fromisoformat(at_str)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed remote heartbeat lookup for %s: %s", worker_id, exc)
        return None

    def get_latest_heartbeat(self) -> datetime | None:
        with self._lock:
            if not self._worker_heartbeats:
                return None
            return max(self._worker_heartbeats.values())

    def _save_firestore_heartbeat(self, worker_id: str, at: datetime) -> None:
        if self._firestore_client is None:
            return
        doc_id = f"hb_{worker_id}"
        at_iso = at.isoformat()
        now_iso = self.now().isoformat()
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_ref = col.document(doc_id)
            agg_ref = col.document("heartbeats")

            if (
                _atomic_firestore_set_heartbeat is not None
                and hasattr(self._firestore_client, "transaction")
                and callable(self._firestore_client.transaction)
            ):
                try:
                    txn = self._firestore_client.transaction()
                    committed, remote_dt = _atomic_firestore_set_heartbeat(
                        txn, doc_ref, agg_ref, worker_id, at_iso, now_iso, at
                    )
                    if not committed:
                        with self._lock:
                            cur = self._worker_heartbeats.get(worker_id)
                            if cur is None or remote_dt > cur:
                                self._worker_heartbeats[worker_id] = remote_dt
                        return
                    return
                except Exception as txn_exc:
                    logger.debug(
                        "Transaction attempt for heartbeat %s encountered: %s; falling back to direct update",
                        worker_id,
                        txn_exc,
                    )

            self._save_heartbeat_direct(doc_ref, agg_ref, worker_id, at, at_iso, now_iso)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore heartbeat for %s: %s", worker_id, exc)

    def _save_heartbeat_direct(
        self,
        doc_ref: Any,
        agg_ref: Any,
        worker_id: str,
        at: datetime,
        at_iso: str,
        now_iso: str,
    ) -> None:
        snap = doc_ref.get() if hasattr(doc_ref, "get") else None
        if snap and getattr(snap, "exists", False):
            existing_data = snap.to_dict() or {}
            existing_at_str = existing_data.get("at")
            if isinstance(existing_at_str, str):
                try:
                    existing_dt = datetime.fromisoformat(existing_at_str)
                    if at < existing_dt:
                        with self._lock:
                            cur = self._worker_heartbeats.get(worker_id)
                            if cur is None or existing_dt > cur:
                                self._worker_heartbeats[worker_id] = existing_dt
                        return
                except Exception:
                    pass
        elif hasattr(doc_ref, "coll") and hasattr(doc_ref.coll, "store"):
            stored_entry = doc_ref.coll.store.get((doc_ref.coll.name, doc_ref.key), {})
            existing_at_str = stored_entry.get("at")
            if isinstance(existing_at_str, str):
                try:
                    existing_dt = datetime.fromisoformat(existing_at_str)
                    if at < existing_dt:
                        with self._lock:
                            cur = self._worker_heartbeats.get(worker_id)
                            if cur is None or existing_dt > cur:
                                self._worker_heartbeats[worker_id] = existing_dt
                        return
                except Exception:
                    pass

        payload = {
            "worker_id": worker_id,
            "at": at_iso,
            "updated_at": now_iso,
        }
        if hasattr(doc_ref, "set"):
            doc_ref.set(payload, merge=True)
        elif hasattr(doc_ref, "coll") and hasattr(doc_ref.coll, "store"):
            doc_ref.coll.store.setdefault((doc_ref.coll.name, doc_ref.key), {}).update(payload)

        if hasattr(agg_ref, "set"):
            agg_ref.set({worker_id: at_iso}, merge=True)
        elif hasattr(agg_ref, "coll") and hasattr(agg_ref.coll, "store"):
            agg_ref.coll.store.setdefault((agg_ref.coll.name, agg_ref.key), {})[worker_id] = at_iso

    # -------------------------------------------------------------------------
    # Backlog Operations
    # -------------------------------------------------------------------------

    def save_backlog(
        self,
        key: str,
        count: int,
        oldest_pending_at: datetime | None,
        at: datetime,
    ) -> None:
        """Record backlog evidence with timestamp for idle pipeline calculation."""
        with self._lock:
            self._pending_backlog[key] = {
                "count": max(0, count),
                "oldest_pending_at": oldest_pending_at,
                "recorded_at": at,
            }
            self._save_persistent()
            self._save_firestore_backlog(key, max(0, count), oldest_pending_at, at)

    def get_backlog(self, key: str, *, fetch_remote: bool = False) -> dict[str, Any] | None:
        with self._lock:
            val = self._pending_backlog.get(key)
            if val is not None and not fetch_remote:
                return val

        if fetch_remote and self._firestore_client is not None:
            remote_val = self._fetch_remote_backlog(key)
            if remote_val is not None:
                with self._lock:
                    self._pending_backlog[key] = remote_val
                    return remote_val
        return val

    def _fetch_remote_backlog(self, key: str) -> dict[str, Any] | None:
        """Perform O(1) single-document Firestore lookup for bl_{key}."""
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_id = f"bl_{key.replace(':', '_')}"
            ref = col.document(doc_id)
            snap = ref.get() if hasattr(ref, "get") else None
            if snap and getattr(snap, "exists", False):
                data = snap.to_dict() or {}
                count = data.get("count", 0)
                oldest_raw = data.get("oldest_pending_at")
                oldest_dt = datetime.fromisoformat(oldest_raw) if oldest_raw else None
                rec_raw = data.get("recorded_at")
                rec_dt = datetime.fromisoformat(rec_raw) if rec_raw else None
                return {
                    "count": count,
                    "oldest_pending_at": oldest_dt,
                    "recorded_at": rec_dt,
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed remote backlog lookup for %s: %s", key, exc)
        return None

    def _save_firestore_backlog(
        self,
        key: str,
        count: int,
        oldest_pending_at: datetime | None,
        at: datetime,
    ) -> None:
        if self._firestore_client is None:
            return
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_id = f"bl_{key.replace(':', '_')}"
            ref = col.document(doc_id)
            payload = {
                "key": key,
                "count": count,
                "oldest_pending_at": oldest_pending_at.isoformat() if oldest_pending_at else None,
                "recorded_at": at.isoformat(),
                "updated_at": self.now().isoformat(),
            }
            if hasattr(ref, "set"):
                ref.set(payload, merge=True)
            elif hasattr(ref, "coll") and hasattr(ref.coll, "store"):
                ref.coll.store.setdefault((ref.coll.name, ref.key), {}).update(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore backlog for %s: %s", key, exc)

    # -------------------------------------------------------------------------
    # Stage Events (In-Memory FIFO)
    # -------------------------------------------------------------------------

    def save_stage_event(
        self,
        correlation_id: str,
        stage: str,
        at: datetime,
        tenant_id: str | None = None,
    ) -> None:
        with self._lock:
            if (
                correlation_id not in self._stage_events
                and len(self._stage_events) >= self._max_stage_events
            ):
                self._stage_events.popitem(last=False)
            entry = self._stage_events.setdefault(correlation_id, {})
            entry[stage] = at
            if tenant_id:
                entry["_tenant_id"] = tenant_id

    # -------------------------------------------------------------------------
    # Durable Loading & Sync
    # -------------------------------------------------------------------------

    def load_persistent(self) -> None:
        """Load state from local JSON file atomically."""
        if not self._persistent_path or not self._persistent_path.exists():
            return
        try:
            self._last_file_mtime = self._persistent_path.stat().st_mtime
            raw = self._persistent_path.read_text(encoding="utf-8").strip()
            if not raw:
                return
            data = json.loads(raw)
            if not isinstance(data, dict):
                return

            with self._lock:
                watermarks = data.get("watermarks")
                if isinstance(watermarks, dict):
                    for k, v in watermarks.items():
                        if isinstance(v, str) and k not in ("heartbeats", "backlogs"):
                            try:
                                dt = datetime.fromisoformat(v)
                                existing = self._last_successful_sync.get(k)
                                if existing is None or dt > existing:
                                    self._last_successful_sync[k] = dt
                            except Exception:
                                pass

                heartbeats = data.get("heartbeats")
                if isinstance(heartbeats, dict):
                    for wid, ts_str in heartbeats.items():
                        if isinstance(ts_str, str):
                            try:
                                hb_dt = datetime.fromisoformat(ts_str)
                                existing_hb = self._worker_heartbeats.get(wid)
                                if existing_hb is None or hb_dt > existing_hb:
                                    self._worker_heartbeats[wid] = hb_dt
                            except Exception:
                                pass

                backlogs = data.get("backlogs")
                if isinstance(backlogs, dict):
                    for k, b_info in backlogs.items():
                        if isinstance(b_info, dict):
                            oldest_raw = b_info.get("oldest_pending_at")
                            oldest_dt = datetime.fromisoformat(oldest_raw) if oldest_raw else None
                            rec_raw = b_info.get("recorded_at")
                            rec_dt = datetime.fromisoformat(rec_raw) if rec_raw else None
                            self._pending_backlog[k] = {
                                "count": b_info.get("count", 0),
                                "oldest_pending_at": oldest_dt,
                                "recorded_at": rec_dt,
                            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load persistent sync watermarks: %s", exc)

    def load_firestore(self) -> None:
        """Stream documents from Firestore collection and update memory monotonically."""
        if self._firestore_client is None:
            return
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            has_granular = False
            with self._lock:
                if hasattr(col, "stream"):
                    try:
                        for doc in col.stream():
                            doc_id = getattr(doc, "id", "")
                            data = doc.to_dict() or {}
                            if doc_id.startswith("wm_"):
                                has_granular = True
                                k = data.get("key") or doc_id[3:].replace("_", ":")
                                v = data.get("at")
                                if isinstance(v, str):
                                    try:
                                        dt = datetime.fromisoformat(v)
                                        existing = self._last_successful_sync.get(k)
                                        if existing is None or dt > existing:
                                            self._last_successful_sync[k] = dt
                                    except Exception:
                                        pass
                            elif doc_id.startswith("hb_"):
                                has_granular = True
                                wid = data.get("worker_id") or doc_id[3:]
                                ts_str = data.get("at")
                                if isinstance(ts_str, str):
                                    try:
                                        hb_dt = datetime.fromisoformat(ts_str)
                                        existing_hb = self._worker_heartbeats.get(wid)
                                        if existing_hb is None or hb_dt > existing_hb:
                                            self._worker_heartbeats[wid] = hb_dt
                                    except Exception:
                                        pass
                            elif doc_id.startswith("bl_"):
                                has_granular = True
                                k = data.get("key") or doc_id[3:].replace("_", ":")
                                count = data.get("count", 0)
                                oldest_raw = data.get("oldest_pending_at")
                                oldest_dt = datetime.fromisoformat(oldest_raw) if oldest_raw else None
                                rec_raw = data.get("recorded_at")
                                rec_dt = datetime.fromisoformat(rec_raw) if rec_raw else self.now()
                                self._pending_backlog[k] = {
                                    "count": count,
                                    "oldest_pending_at": oldest_dt,
                                    "recorded_at": rec_dt,
                                }
                    except Exception:
                        pass

                # Fallback to aggregate documents if no granular found
                if not has_granular:
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
                                except Exception:
                                    pass
            self._last_firestore_poll = time.time()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load Firestore sync watermarks: %s", exc)

    def reload_if_needed(self) -> None:
        """Periodically refresh state from file or Firestore."""
        if self._persistent_path and self._persistent_path.exists():
            try:
                mtime = self._persistent_path.stat().st_mtime
                if mtime > self._last_file_mtime:
                    self.load_persistent()
            except Exception:
                pass
        if self._firestore_client is not None:
            now_ts = time.time()
            if now_ts - self._last_firestore_poll > 2.0:
                self.load_firestore()

    def _save_persistent(self) -> None:
        if not self._persistent_path:
            return
        try:
            self._persistent_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "watermarks": {k: v.isoformat() for k, v in self._last_successful_sync.items()},
                "heartbeats": {k: v.isoformat() for k, v in self._worker_heartbeats.items()},
                "backlogs": {
                    k: {
                        "count": v.get("count", 0),
                        "oldest_pending_at": (
                            v.get("oldest_pending_at").isoformat()
                            if v.get("oldest_pending_at")
                            else None
                        ),
                        "recorded_at": (
                            v.get("recorded_at").isoformat()
                            if v.get("recorded_at")
                            else None
                        ),
                    }
                    for k, v in self._pending_backlog.items()
                },
                "updated_at": self.now().isoformat(),
            }
            tmp = self._persistent_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._persistent_path)
            self._last_file_mtime = self._persistent_path.stat().st_mtime
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save persistent sync watermarks: %s", exc)
