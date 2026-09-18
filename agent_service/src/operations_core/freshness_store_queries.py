"""Query and load surfaces for FreshnessStore."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

from operations_core.freshness_firestore_ops import parse_iso_datetime

logger = logging.getLogger(__name__)


def _merge_watermark(memory: dict[str, datetime], key: str, value: Any) -> None:
    dt = parse_iso_datetime(value)
    if dt is None:
        return
    existing = memory.get(key)
    if existing is None or dt > existing:
        memory[key] = dt


def _merge_heartbeat(memory: dict[str, datetime], worker_id: str, value: Any) -> None:
    hb_dt = parse_iso_datetime(value)
    if hb_dt is None:
        return
    existing = memory.get(worker_id)
    if existing is None or hb_dt > existing:
        memory[worker_id] = hb_dt


def _parse_backlog_entry(
    data: dict[str, Any], *, default_recorded: datetime | None = None
) -> dict[str, Any]:
    oldest_raw = data.get("oldest_pending_at")
    oldest_dt = parse_iso_datetime(oldest_raw) if oldest_raw else None
    rec_raw = data.get("recorded_at")
    rec_dt = parse_iso_datetime(rec_raw) if rec_raw else default_recorded
    return {
        "count": data.get("count", 0),
        "oldest_pending_at": oldest_dt,
        "recorded_at": rec_dt,
    }


def _apply_firestore_document(
    store: FreshnessStoreQueries,
    doc_id: str,
    data: dict[str, Any],
) -> bool:
    """Apply one granular Firestore document. Returns True if granular."""
    if doc_id.startswith("wm_"):
        key = data.get("key") or doc_id[3:].replace("_", ":")
        _merge_watermark(store.last_successful_sync, key, data.get("at"))
        return True
    if doc_id.startswith("hb_"):
        worker_id = data.get("worker_id") or doc_id[3:]
        _merge_heartbeat(store.worker_heartbeats, worker_id, data.get("at"))
        return True
    if doc_id.startswith("bl_"):
        key = data.get("key") or doc_id[3:].replace("_", ":")
        store.pending_backlog[key] = _parse_backlog_entry(
            data, default_recorded=store.now()
        )
        return True
    return False


def _load_firestore_aggregates(store: FreshnessStoreQueries, col: Any) -> None:
    wm_ref = col.document("watermarks")
    snap_wm = wm_ref.get() if hasattr(wm_ref, "get") else None
    if snap_wm and getattr(snap_wm, "exists", False):
        for key, value in (snap_wm.to_dict() or {}).items():
            _merge_watermark(store.last_successful_sync, key, value)

    hb_ref = col.document("heartbeats")
    snap_hb = hb_ref.get() if hasattr(hb_ref, "get") else None
    if snap_hb and getattr(snap_hb, "exists", False):
        for worker_id, ts_str in (snap_hb.to_dict() or {}).items():
            _merge_heartbeat(store.worker_heartbeats, worker_id, ts_str)


class FreshnessStoreQueries:
    """Mixin providing read, remote lookup, and durable load surfaces."""

    lock: Any
    _persistent_path: Any
    _firestore_client: Any
    _firestore_collection: str
    last_successful_sync: dict[str, datetime]
    worker_heartbeats: dict[str, datetime]
    pending_backlog: dict[str, dict[str, Any]]
    last_file_mtime: float
    last_firestore_poll: float

    def now(self) -> datetime:  # pragma: no cover - provided by FreshnessStore
        raise NotImplementedError

    def get_watermark(self, key: str, *, fetch_remote: bool = False) -> datetime | None:
        """Return the latest watermark for key with optional targeted Firestore lookup."""
        with self.lock:
            val = self.last_successful_sync.get(key)
            if val is not None and not fetch_remote:
                return val

        if fetch_remote and self._firestore_client is not None:
            remote_val = self._fetch_remote_watermark(key)
            if remote_val is not None:
                with self.lock:
                    cur = self.last_successful_sync.get(key)
                    if cur is None or remote_val > cur:
                        self.last_successful_sync[key] = remote_val
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
                return parse_iso_datetime((snap.to_dict() or {}).get("at"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed remote watermark lookup for %s: %s", key, exc)
        return None

    def get_heartbeat(
        self, worker_id: str, *, fetch_remote: bool = False
    ) -> datetime | None:
        with self.lock:
            val = self.worker_heartbeats.get(worker_id)
            if val is not None and not fetch_remote:
                return val

        if fetch_remote and self._firestore_client is not None:
            remote_val = self._fetch_remote_heartbeat(worker_id)
            if remote_val is not None:
                with self.lock:
                    cur = self.worker_heartbeats.get(worker_id)
                    if cur is None or remote_val > cur:
                        self.worker_heartbeats[worker_id] = remote_val
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
                return parse_iso_datetime((snap.to_dict() or {}).get("at"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed remote heartbeat lookup for %s: %s", worker_id, exc)
        return None

    def get_latest_heartbeat(self) -> datetime | None:
        with self.lock:
            if not self.worker_heartbeats:
                return None
            return max(self.worker_heartbeats.values())

    def get_backlog(
        self, key: str, *, fetch_remote: bool = False
    ) -> dict[str, Any] | None:
        with self.lock:
            val = self.pending_backlog.get(key)
            if val is not None and not fetch_remote:
                return val

        if fetch_remote and self._firestore_client is not None:
            remote_val = self._fetch_remote_backlog(key)
            if remote_val is not None:
                with self.lock:
                    self.pending_backlog[key] = remote_val
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
                return _parse_backlog_entry(snap.to_dict() or {})
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed remote backlog lookup for %s: %s", key, exc)
        return None

    def load_persistent(self) -> None:
        """Load state from local JSON file atomically."""
        if not self._persistent_path or not self._persistent_path.exists():
            return
        try:
            self.last_file_mtime = self._persistent_path.stat().st_mtime
            raw = self._persistent_path.read_text(encoding="utf-8").strip()
            if not raw:
                return
            data = json.loads(raw)
            if not isinstance(data, dict):
                return
            self._apply_persistent_payload(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load persistent sync watermarks: %s", exc)

    def _apply_persistent_payload(self, data: dict[str, Any]) -> None:
        with self.lock:
            watermarks = data.get("watermarks")
            if isinstance(watermarks, dict):
                for key, value in watermarks.items():
                    if isinstance(value, str) and key not in ("heartbeats", "backlogs"):
                        _merge_watermark(self.last_successful_sync, key, value)

            heartbeats = data.get("heartbeats")
            if isinstance(heartbeats, dict):
                for worker_id, ts_str in heartbeats.items():
                    _merge_heartbeat(self.worker_heartbeats, worker_id, ts_str)

            backlogs = data.get("backlogs")
            if isinstance(backlogs, dict):
                for key, info in backlogs.items():
                    if isinstance(info, dict):
                        self.pending_backlog[key] = _parse_backlog_entry(info)

    def load_firestore(self) -> None:
        """Stream documents from Firestore collection and update memory monotonically."""
        if self._firestore_client is None:
            return
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            has_granular = False
            with self.lock:
                if hasattr(col, "stream"):
                    try:
                        for doc in col.stream():
                            doc_id = getattr(doc, "id", "")
                            data = doc.to_dict() or {}
                            if _apply_firestore_document(self, doc_id, data):
                                has_granular = True
                    except Exception:
                        pass
                if not has_granular:
                    _load_firestore_aggregates(self, col)
            self.last_firestore_poll = time.time()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load Firestore sync watermarks: %s", exc)

    def reload_if_needed(self) -> None:
        """Periodically refresh state from file or Firestore."""
        if self._persistent_path and self._persistent_path.exists():
            try:
                mtime = self._persistent_path.stat().st_mtime
                if mtime > self.last_file_mtime:
                    self.load_persistent()
            except Exception:
                pass
        if self._firestore_client is not None:
            now_ts = time.time()
            if now_ts - self.last_firestore_poll > 2.0:
                self.load_firestore()


__all__ = ["FreshnessStoreQueries"]
