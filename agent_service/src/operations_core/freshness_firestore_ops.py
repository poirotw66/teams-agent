"""Firestore transaction and direct-write helpers for freshness state."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    from google.cloud import firestore

    @firestore.transactional
    def atomic_firestore_set_watermark(
        transaction: Any,
        doc_ref: Any,
        agg_ref: Any,
        key: str,
        at_iso: str,
        updated_at_iso: str,
        at_dt: datetime,
    ) -> tuple[bool, datetime]:
        """Atomically read and advance watermark only if newer (monotonic)."""
        return _atomic_advance(
            transaction,
            doc_ref,
            agg_ref,
            entity_field="key",
            entity_id=key,
            at_iso=at_iso,
            updated_at_iso=updated_at_iso,
            at_dt=at_dt,
        )

    @firestore.transactional
    def atomic_firestore_set_heartbeat(
        transaction: Any,
        doc_ref: Any,
        agg_ref: Any,
        worker_id: str,
        at_iso: str,
        updated_at_iso: str,
        at_dt: datetime,
    ) -> tuple[bool, datetime]:
        """Atomically read and advance worker heartbeat only if newer (monotonic)."""
        return _atomic_advance(
            transaction,
            doc_ref,
            agg_ref,
            entity_field="worker_id",
            entity_id=worker_id,
            at_iso=at_iso,
            updated_at_iso=updated_at_iso,
            at_dt=at_dt,
        )

except Exception:  # pragma: no cover - optional runtime dependency
    atomic_firestore_set_watermark = None
    atomic_firestore_set_heartbeat = None


def _atomic_advance(
    transaction: Any,
    doc_ref: Any,
    agg_ref: Any,
    *,
    entity_field: str,
    entity_id: str,
    at_iso: str,
    updated_at_iso: str,
    at_dt: datetime,
) -> tuple[bool, datetime]:
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
        entity_field: entity_id,
        "at": at_iso,
        "updated_at": updated_at_iso,
    }
    transaction.set(doc_ref, payload, merge=True)
    if agg_ref is not None and hasattr(agg_ref, "set"):
        transaction.set(agg_ref, {entity_id: at_iso}, merge=True)
    return True, at_dt


def parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def read_document_at(doc_ref: Any) -> datetime | None:
    """Read monotonic ``at`` from a Firestore ref or lightweight mock store."""
    snap = doc_ref.get() if hasattr(doc_ref, "get") else None
    if snap and getattr(snap, "exists", False):
        return parse_iso_datetime((snap.to_dict() or {}).get("at"))
    if hasattr(doc_ref, "coll") and hasattr(doc_ref.coll, "store"):
        stored_entry = doc_ref.coll.store.get((doc_ref.coll.name, doc_ref.key), {})
        return parse_iso_datetime(stored_entry.get("at"))
    return None


def write_doc_and_aggregate(
    doc_ref: Any,
    agg_ref: Any,
    *,
    payload: dict[str, Any],
    agg_key: str,
    at_iso: str,
) -> None:
    if hasattr(doc_ref, "set"):
        doc_ref.set(payload, merge=True)
    elif hasattr(doc_ref, "coll") and hasattr(doc_ref.coll, "store"):
        doc_ref.coll.store.setdefault((doc_ref.coll.name, doc_ref.key), {}).update(payload)

    if hasattr(agg_ref, "set"):
        agg_ref.set({agg_key: at_iso}, merge=True)
    elif hasattr(agg_ref, "coll") and hasattr(agg_ref.coll, "store"):
        agg_ref.coll.store.setdefault((agg_ref.coll.name, agg_ref.key), {})[agg_key] = at_iso


def adopt_remote_if_newer(
    lock: Any,
    memory: dict[str, datetime],
    entity_id: str,
    remote_dt: datetime,
) -> None:
    with lock:
        current = memory.get(entity_id)
        if current is None or remote_dt > current:
            memory[entity_id] = remote_dt


def save_monotonic_direct(
    *,
    doc_ref: Any,
    agg_ref: Any,
    entity_id: str,
    at: datetime,
    at_iso: str,
    payload: dict[str, Any],
    memory: dict[str, datetime],
    lock: Any,
) -> None:
    existing_dt = read_document_at(doc_ref)
    if existing_dt is not None and at < existing_dt:
        adopt_remote_if_newer(lock, memory, entity_id, existing_dt)
        return
    write_doc_and_aggregate(
        doc_ref, agg_ref, payload=payload, agg_key=entity_id, at_iso=at_iso
    )


def commit_atomic_or_direct(
    *,
    firestore_client: Any,
    atomic_fn: Callable[..., tuple[bool, datetime]] | None,
    doc_ref: Any,
    agg_ref: Any,
    entity_id: str,
    at: datetime,
    at_iso: str,
    now_iso: str,
    memory: dict[str, datetime],
    lock: Any,
    kind: str,
    direct_payload: dict[str, Any],
) -> None:
    """Prefer transactional advance; fall back to direct write only without transactions."""
    if (
        atomic_fn is not None
        and hasattr(firestore_client, "transaction")
        and callable(firestore_client.transaction)
    ):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                txn = firestore_client.transaction()
                committed, remote_dt = atomic_fn(
                    txn, doc_ref, agg_ref, entity_id, at_iso, now_iso, at
                )
                if not committed:
                    adopt_remote_if_newer(lock, memory, entity_id, remote_dt)
                return
            except Exception as txn_exc:
                if attempt < max_retries - 1:
                    time.sleep(0.05 * (2**attempt))
                    continue
                logger.error(
                    "Firestore atomic transaction failed for %s %s after %d attempts: %s; "
                    "aborted without non-atomic downgrade",
                    kind,
                    entity_id,
                    max_retries,
                    txn_exc,
                )
                raise RuntimeError(
                    f"Firestore {kind} transaction failed for {entity_id}: {txn_exc}"
                ) from txn_exc

    save_monotonic_direct(
        doc_ref=doc_ref,
        agg_ref=agg_ref,
        entity_id=entity_id,
        at=at,
        at_iso=at_iso,
        payload=direct_payload,
        memory=memory,
        lock=lock,
    )


def save_firestore_backlog_document(
    *,
    firestore_client: Any,
    collection_name: str,
    key: str,
    count: int,
    oldest_pending_at: datetime | None,
    at: datetime,
    updated_at_iso: str,
) -> None:
    if firestore_client is None:
        return
    try:
        col = firestore_client.collection(collection_name)
        doc_id = f"bl_{key.replace(':', '_')}"
        ref = col.document(doc_id)
        payload = {
            "key": key,
            "count": count,
            "oldest_pending_at": oldest_pending_at.isoformat() if oldest_pending_at else None,
            "recorded_at": at.isoformat(),
            "updated_at": updated_at_iso,
        }
        if hasattr(ref, "set"):
            ref.set(payload, merge=True)
        elif hasattr(ref, "coll") and hasattr(ref.coll, "store"):
            ref.coll.store.setdefault((ref.coll.name, ref.key), {}).update(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save Firestore backlog for %s: %s", key, exc)


__all__ = [
    "adopt_remote_if_newer",
    "atomic_firestore_set_heartbeat",
    "atomic_firestore_set_watermark",
    "commit_atomic_or_direct",
    "parse_iso_datetime",
    "read_document_at",
    "save_firestore_backlog_document",
    "save_monotonic_direct",
    "write_doc_and_aggregate",
]
