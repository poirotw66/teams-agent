from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol


class ExportJobStore(Protocol):
    async def get(self, job_id: str) -> dict[str, Any] | None: ...

    async def put(self, job_id: str, payload: dict[str, Any]) -> None: ...

    async def delete(self, job_id: str) -> None: ...

    async def list_expired(self, before: datetime) -> list[dict[str, Any]]: ...

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]: ...

    async def list_all_content_refs(self) -> set[str]:
        """Return every durable ``content_ref``. Must be complete (no page caps)."""
        ...

    async def find_by_idempotency_scope(
        self,
        *,
        key: str,
        tenant_id: str,
        requester_id: str,
    ) -> dict[str, Any] | None: ...

    async def claim_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> dict[str, Any] | None: ...

    async def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
        now: datetime,
    ) -> bool: ...

    async def complete_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool: ...

    async def requeue_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool: ...


def _lease_expired(payload: dict[str, Any], now: datetime) -> bool:
    raw = payload.get("lease_expires_at")
    if not raw:
        return True
    if isinstance(raw, datetime):
        expires = raw
    else:
        expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return expires <= now


def _apply_claim(
    payload: dict[str, Any],
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime,
) -> dict[str, Any]:
    claimed = dict(payload)
    claimed["status"] = "RUNNING"
    claimed["lease_owner"] = worker_id
    claimed["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
    claimed["lease_token"] = uuid.uuid4().hex
    claimed["attempt_count"] = int(claimed.get("attempt_count") or 0) + 1
    claimed["error"] = None
    return claimed


class FileExportJobStore:
    """Durable metadata store with process-safe atomic claim via flock.

    The exclusive lock is held on a dedicated ``export_jobs.lock`` file so
    ``os.replace`` of the JSON payload cannot drop the flock inode/handle that
    other processes wait on.
    """

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._path = root / "export_jobs.json"
        self._lock_path = root / "export_jobs.lock"
        self._lock = threading.RLock()

    def _exclusive(self):
        class _Guard:
            def __init__(self, store: FileExportJobStore) -> None:
                self._store = store
                self._handle = None

            def __enter__(self):
                self._store._lock.acquire()
                self._store._lock_path.parent.mkdir(parents=True, exist_ok=True)
                # Dedicated lock file — never replaced by JSON writes.
                self._handle = self._store._lock_path.open("a+", encoding="utf-8")
                try:
                    import fcntl

                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
                except (ImportError, OSError):
                    # Windows / unsupported FS: threading lock still serializes in-process.
                    pass
                if not self._store._path.exists():
                    self._store._path.write_text("[]", encoding="utf-8")
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                try:
                    if self._handle is not None:
                        try:
                            import fcntl

                            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                        except (ImportError, OSError):
                            pass
                        self._handle.close()
                finally:
                    self._store._lock.release()

        return _Guard(self)

    def _read_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return {str(item["job_id"]): item for item in payload}
        return {str(key): value for key, value in payload.items()}

    def _write_unlocked(self, jobs: dict[str, dict[str, Any]]) -> None:
        temporary = self._path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(list(jobs.values()), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        with self._exclusive():
            return self._read_unlocked().get(job_id)

    async def put(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._exclusive():
            jobs = self._read_unlocked()
            jobs[job_id] = payload
            self._write_unlocked(jobs)

    async def delete(self, job_id: str) -> None:
        with self._exclusive():
            jobs = self._read_unlocked()
            jobs.pop(job_id, None)
            self._write_unlocked(jobs)

    async def list_expired(self, before: datetime) -> list[dict[str, Any]]:
        with self._exclusive():
            return [
                payload
                for payload in self._read_unlocked().values()
                if payload.get("status") in {"COMPLETED", "FAILED"}
                and isinstance(payload.get("expires_at"), str)
                and datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
                <= before
            ]

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]:
        with self._exclusive():
            return [
                payload
                for payload in self._read_unlocked().values()
                if payload.get("status") in statuses
            ]

    async def list_all_content_refs(self) -> set[str]:
        with self._exclusive():
            refs: set[str] = set()
            for payload in self._read_unlocked().values():
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
        with self._exclusive():
            for payload in self._read_unlocked().values():
                if payload.get("idempotency_key") != key:
                    continue
                if payload.get("tenant_id") != tenant_id:
                    continue
                if payload.get("requested_by") != requester_id:
                    continue
                if payload.get("status") in {"FAILED", "EXPIRED"}:
                    continue
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
        with self._exclusive():
            jobs = self._read_unlocked()
            current = jobs.get(job_id)
            if current is None:
                return None
            status = current.get("status")
            if status == "QUEUED":
                claimed = _apply_claim(
                    current, worker_id=worker_id, lease_seconds=lease_seconds, now=now
                )
            elif status == "RUNNING":
                # Never steal a still-valid lease — including the caller's own —
                # so recovery scanners cannot double-dispatch in-flight work.
                if not _lease_expired(current, now):
                    return None
                claimed = _apply_claim(
                    current, worker_id=worker_id, lease_seconds=lease_seconds, now=now
                )
            else:
                return None
            jobs[job_id] = claimed
            self._write_unlocked(jobs)
            return claimed

    async def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
        now: datetime,
    ) -> bool:
        with self._exclusive():
            jobs = self._read_unlocked()
            current = jobs.get(job_id)
            if current is None:
                return False
            if current.get("status") != "RUNNING":
                return False
            if current.get("lease_owner") != worker_id:
                return False
            if current.get("lease_token") != lease_token:
                return False
            current = dict(current)
            current["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
            jobs[job_id] = current
            self._write_unlocked(jobs)
            return True

    async def complete_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool:
        with self._exclusive():
            jobs = self._read_unlocked()
            current = jobs.get(job_id)
            if current is None:
                return False
            if current.get("status") != "RUNNING":
                return False
            if current.get("lease_owner") != worker_id:
                return False
            if current.get("lease_token") != lease_token:
                return False
            next_payload = dict(payload)
            next_payload["lease_owner"] = None
            next_payload["lease_expires_at"] = None
            next_payload["lease_token"] = None
            jobs[job_id] = next_payload
            self._write_unlocked(jobs)
            return True

    async def requeue_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool:
        with self._exclusive():
            jobs = self._read_unlocked()
            current = jobs.get(job_id)
            if current is None:
                return False
            if current.get("status") != "RUNNING":
                return False
            if current.get("lease_owner") != worker_id:
                return False
            if current.get("lease_token") != lease_token:
                return False
            next_payload = dict(payload)
            next_payload["status"] = "QUEUED"
            next_payload["lease_owner"] = None
            next_payload["lease_expires_at"] = None
            next_payload["lease_token"] = None
            jobs[job_id] = next_payload
            self._write_unlocked(jobs)
            return True


class FirestoreExportJobStore:
    """Multi-instance metadata store backed by one Firestore collection."""

    def __init__(self, client: Any, collection: str) -> None:
        self._collection = client.collection(collection)
        self._client = client

    async def get(self, job_id: str) -> dict[str, Any] | None:
        snapshot = await self._collection.document(job_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def put(self, job_id: str, payload: dict[str, Any]) -> None:
        firestore_payload = dict(payload)
        for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
            value = firestore_payload.get(key)
            if isinstance(value, str):
                firestore_payload[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        await self._collection.document(job_id).set(firestore_payload)

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
            payload
            for payload in snapshots
            if payload.get("status") in {"COMPLETED", "FAILED"}
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
                claimed = _apply_claim(
                    current, worker_id=worker_id, lease_seconds=lease_seconds, now=now
                )
            elif status == "RUNNING":
                if not _lease_expired(current, now):
                    return None
                claimed = _apply_claim(
                    current, worker_id=worker_id, lease_seconds=lease_seconds, now=now
                )
            else:
                return None
            for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
                value = claimed.get(key)
                if isinstance(value, str):
                    claimed[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            txn.set(doc_ref, claimed)
            # Return JSON-serializable copy for callers.
            result = dict(claimed)
            for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
                value = result.get(key)
                if isinstance(value, datetime):
                    result[key] = value.isoformat()
            return result

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
        if current.get("status") != "RUNNING":
            return False
        if current.get("lease_owner") != worker_id or current.get("lease_token") != lease_token:
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
            if current.get("status") != "RUNNING":
                return False
            if current.get("lease_owner") != worker_id:
                return False
            if current.get("lease_token") != lease_token:
                return False
            next_payload = dict(payload)
            next_payload["lease_owner"] = None
            next_payload["lease_expires_at"] = None
            next_payload["lease_token"] = None
            for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
                value = next_payload.get(key)
                if isinstance(value, str):
                    next_payload[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
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
            if current.get("status") != "RUNNING":
                return False
            if current.get("lease_owner") != worker_id:
                return False
            if current.get("lease_token") != lease_token:
                return False
            next_payload = dict(payload)
            next_payload["status"] = "QUEUED"
            next_payload["lease_owner"] = None
            next_payload["lease_expires_at"] = None
            next_payload["lease_token"] = None
            for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
                value = next_payload.get(key)
                if isinstance(value, str):
                    next_payload[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            txn.set(doc_ref, next_payload)
            return True

        return bool(_requeue(transaction))
