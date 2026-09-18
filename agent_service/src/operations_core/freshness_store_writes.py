"""Write-side operations for FreshnessStore (watermarks, heartbeats, backlog, stage)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from operations_core.freshness_firestore_ops import (
    atomic_firestore_set_heartbeat,
    atomic_firestore_set_watermark,
    commit_atomic_or_direct,
    save_firestore_backlog_document,
)

logger = logging.getLogger(__name__)


class FreshnessStoreWrites:
    """Mixin providing durable and Firestore write surfaces for FreshnessStore."""

    lock: Any
    _persistent_path: Any
    _firestore_client: Any
    _firestore_collection: str
    _max_stage_events: int
    last_successful_sync: dict[str, datetime]
    worker_heartbeats: dict[str, datetime]
    pending_backlog: dict[str, dict[str, Any]]
    stage_events: Any
    last_file_mtime: float

    def now(self) -> datetime:  # pragma: no cover - provided by FreshnessStore
        raise NotImplementedError

    def save_watermark(self, key: str, at: datetime) -> None:
        """Atomically advance the watermark for a given resource key."""
        with self.lock:
            existing = self.last_successful_sync.get(key)
            if existing is not None and at < existing:
                return
            self.last_successful_sync[key] = at
            self.save_persistent()
            self.save_firestore_watermark(key, at)

    def save_firestore_watermark(self, key: str, at: datetime) -> None:
        if self._firestore_client is None:
            return
        doc_id = f"wm_{key.replace(':', '_')}"
        at_iso = at.isoformat()
        now_iso = self.now().isoformat()
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_ref = col.document(doc_id)
            agg_ref = col.document("watermarks")
            commit_atomic_or_direct(
                firestore_client=self._firestore_client,
                atomic_fn=atomic_firestore_set_watermark,
                doc_ref=doc_ref,
                agg_ref=agg_ref,
                entity_id=key,
                at=at,
                at_iso=at_iso,
                now_iso=now_iso,
                memory=self.last_successful_sync,
                lock=self.lock,
                kind="watermark",
                direct_payload={"key": key, "at": at_iso, "updated_at": now_iso},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore watermark for %s: %s", key, exc)
            if hasattr(self._firestore_client, "transaction") and callable(
                self._firestore_client.transaction
            ):
                raise

    def save_heartbeat(self, worker_id: str, at: datetime) -> None:
        """Atomically advance the heartbeat timestamp for a worker."""
        with self.lock:
            existing = self.worker_heartbeats.get(worker_id)
            if existing is not None and at < existing:
                return
            self.worker_heartbeats[worker_id] = at
            self.save_persistent()
            self.save_firestore_heartbeat(worker_id, at)

    def save_firestore_heartbeat(self, worker_id: str, at: datetime) -> None:
        if self._firestore_client is None:
            return
        doc_id = f"hb_{worker_id}"
        at_iso = at.isoformat()
        now_iso = self.now().isoformat()
        try:
            col = self._firestore_client.collection(self._firestore_collection)
            doc_ref = col.document(doc_id)
            agg_ref = col.document("heartbeats")
            commit_atomic_or_direct(
                firestore_client=self._firestore_client,
                atomic_fn=atomic_firestore_set_heartbeat,
                doc_ref=doc_ref,
                agg_ref=agg_ref,
                entity_id=worker_id,
                at=at,
                at_iso=at_iso,
                now_iso=now_iso,
                memory=self.worker_heartbeats,
                lock=self.lock,
                kind="heartbeat",
                direct_payload={
                    "worker_id": worker_id,
                    "at": at_iso,
                    "updated_at": now_iso,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save Firestore heartbeat for %s: %s", worker_id, exc)
            if hasattr(self._firestore_client, "transaction") and callable(
                self._firestore_client.transaction
            ):
                raise

    def save_backlog(
        self,
        key: str,
        count: int,
        oldest_pending_at: datetime | None,
        at: datetime,
    ) -> None:
        """Record backlog evidence with timestamp for idle pipeline calculation."""
        with self.lock:
            self.pending_backlog[key] = {
                "count": max(0, count),
                "oldest_pending_at": oldest_pending_at,
                "recorded_at": at,
            }
            self.save_persistent()
            save_firestore_backlog_document(
                firestore_client=self._firestore_client,
                collection_name=self._firestore_collection,
                key=key,
                count=max(0, count),
                oldest_pending_at=oldest_pending_at,
                at=at,
                updated_at_iso=self.now().isoformat(),
            )

    def save_stage_event(
        self,
        correlation_id: str,
        stage: str,
        at: datetime,
        tenant_id: str | None = None,
    ) -> None:
        with self.lock:
            if (
                correlation_id not in self.stage_events
                and len(self.stage_events) >= self._max_stage_events
            ):
                self.stage_events.popitem(last=False)
            entry = self.stage_events.setdefault(correlation_id, {})
            entry[stage] = at
            if tenant_id:
                entry["_tenant_id"] = tenant_id

    def save_persistent(self) -> None:
        if not self._persistent_path:
            return
        try:
            self._persistent_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "watermarks": {
                    k: v.isoformat() for k, v in self.last_successful_sync.items()
                },
                "heartbeats": {
                    k: v.isoformat() for k, v in self.worker_heartbeats.items()
                },
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
                    for k, v in self.pending_backlog.items()
                },
                "updated_at": self.now().isoformat(),
            }
            tmp = self._persistent_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._persistent_path)
            self.last_file_mtime = self._persistent_path.stat().st_mtime
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save persistent sync watermarks: %s", exc)


__all__ = ["FreshnessStoreWrites"]
