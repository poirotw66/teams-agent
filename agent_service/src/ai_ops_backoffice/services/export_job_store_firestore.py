"""Firestore-backed multi-instance export job metadata store."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .export_job_lease import (
    apply_claim,
    clear_lease_fields,
    lease_expired,
    owns_running_lease,
    parse_firestore_timestamps,
    serialize_firestore_timestamps,
)


class FirestoreExportJobStore:
    """Multi-instance metadata store backed by one Firestore collection."""

    def __init__(self, client: Any, collection: str) -> None:
        self._collection = client.collection(collection)
        self._client = client

    async def get(self, job_id: str) -> dict[str, Any] | None:
        snapshot = await self._collection.document(job_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def put(self, job_id: str, payload: dict[str, Any]) -> None:
        await self._collection.document(job_id).set(parse_firestore_timestamps(payload))

    async def delete(self, job_id: str) -> None:
        await self._collection.document(job_id).delete()

    async def _stream_where(
        self,
        *,
        field: str,
        op: str,
        value: Any,
        page_size: int = 200,
    ) -> list[dict[str, Any]]:
        """Page through a Firestore equality/range query without a hard row cap."""
        from google.cloud.firestore_v1.base_query import FieldFilter

        results: list[dict[str, Any]] = []
        last_snapshot = None
        while True:
            query = (
                self._collection.where(filter=FieldFilter(field, op, value))
                .order_by("__name__")
                .limit(page_size)
            )
            if last_snapshot is not None:
                query = query.start_after(last_snapshot)
            batch = [snapshot async for snapshot in query.stream()]
            if not batch:
                break
            for snapshot in batch:
                payload = snapshot.to_dict()
                if payload is not None:
                    results.append(payload)
            last_snapshot = batch[-1]
            if len(batch) < page_size:
                break
        return results

    async def list_expired(self, before: datetime) -> list[dict[str, Any]]:
        snapshots = await self._stream_where(field="expires_at", op="<=", value=before)
        return [
            payload for payload in snapshots if payload.get("status") in {"COMPLETED", "FAILED"}
        ]

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for status in statuses:
            results.extend(await self._stream_where(field="status", op="==", value=status))
        return results

    async def list_all_content_refs(self) -> set[str]:
        """Scan every status fully so purge never treats capped pages as complete."""
        refs: set[str] = set()
        for status in ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "EXPIRED"):
            for payload in await self._stream_where(field="status", op="==", value=status):
                ref = payload.get("content_ref")
                if isinstance(ref, str) and ref:
                    refs.add(ref)
        return refs

    async def find_by_idempotency_scope(
        self,
        *,
        key: str,
        tenant_id: str,
        requester_id: str,
    ) -> dict[str, Any] | None:
        if not key:
            return None
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self._collection.where(filter=FieldFilter("idempotency_key", "==", key))
            .where(filter=FieldFilter("tenant_id", "==", tenant_id))
            .where(filter=FieldFilter("requested_by", "==", requester_id))
            .limit(5)
        )
        async for snapshot in query.stream():
            payload = snapshot.to_dict()
            if payload.get("status") not in {"FAILED", "EXPIRED"}:
                return payload
        return None

    async def claim_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> dict[str, Any] | None:
        # Firestore transaction claim for multi-worker mutual exclusion.
        transaction = self._client.transaction()
        doc_ref = self._collection.document(job_id)

        @transaction.transactional
        def _claim(txn: Any) -> dict[str, Any] | None:
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            current = snapshot.to_dict()
            status = current.get("status")
            if status == "QUEUED":
                claimed = apply_claim(
                    current, worker_id=worker_id, lease_seconds=lease_seconds, now=now
                )
            elif status == "RUNNING":
                if not lease_expired(current, now):
                    return None
                claimed = apply_claim(
                    current, worker_id=worker_id, lease_seconds=lease_seconds, now=now
                )
            else:
                return None
            claimed = parse_firestore_timestamps(claimed)
            txn.set(doc_ref, claimed)
            return serialize_firestore_timestamps(claimed)

        return _claim(transaction)

    async def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
        now: datetime,
    ) -> bool:
        current = await self.get(job_id)
        if current is None:
            return False
        if not owns_running_lease(current, worker_id=worker_id, lease_token=lease_token):
            return False
        current["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
        await self.put(job_id, current)
        return True

    async def complete_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool:
        transaction = self._client.transaction()
        doc_ref = self._collection.document(job_id)

        @transaction.transactional
        def _complete(txn: Any) -> bool:
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return False
            current = snapshot.to_dict()
            if not owns_running_lease(current, worker_id=worker_id, lease_token=lease_token):
                return False
            next_payload = parse_firestore_timestamps(clear_lease_fields(payload))
            txn.set(doc_ref, next_payload)
            return True

        return bool(_complete(transaction))

    async def requeue_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool:
        transaction = self._client.transaction()
        doc_ref = self._collection.document(job_id)

        @transaction.transactional
        def _requeue(txn: Any) -> bool:
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return False
            current = snapshot.to_dict()
            if not owns_running_lease(current, worker_id=worker_id, lease_token=lease_token):
                return False
            next_payload = clear_lease_fields(payload)
            next_payload["status"] = "QUEUED"
            next_payload = parse_firestore_timestamps(next_payload)
            txn.set(doc_ref, next_payload)
            return True

        return bool(_requeue(transaction))
