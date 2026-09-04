from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


class ExportJobStore(Protocol):
    async def get(self, job_id: str) -> dict[str, Any] | None:
        ...

    async def put(self, job_id: str, payload: dict[str, Any]) -> None:
        ...

    async def delete(self, job_id: str) -> None:
        ...

    async def list_expired(self, before: datetime) -> list[dict[str, Any]]:
        ...

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]:
        ...

    async def find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        ...


class FileExportJobStore:
    """Durable single-instance metadata store."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._path = root / "export_jobs.json"

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return {str(item["job_id"]): item for item in payload}
        return {str(key): value for key, value in payload.items()}

    def _write(self, jobs: dict[str, dict[str, Any]]) -> None:
        temporary = self._path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(list(jobs.values()), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        return self._read().get(job_id)

    async def put(self, job_id: str, payload: dict[str, Any]) -> None:
        jobs = self._read()
        jobs[job_id] = payload
        self._write(jobs)

    async def delete(self, job_id: str) -> None:
        jobs = self._read()
        jobs.pop(job_id, None)
        self._write(jobs)

    async def list_expired(self, before: datetime) -> list[dict[str, Any]]:
        return [
            payload
            for payload in self._read().values()
            if payload.get("status") in {"COMPLETED", "FAILED"}
            and isinstance(payload.get("expires_at"), str)
            and datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
            <= before
        ]

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]:
        return [
            payload
            for payload in self._read().values()
            if payload.get("status") in statuses
        ]

    async def find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        for payload in self._read().values():
            if payload.get("idempotency_key") == key and payload.get("status") not in {
                "FAILED",
                "EXPIRED",
            }:
                return payload
        return None


class FirestoreExportJobStore:
    """Multi-instance metadata store backed by one Firestore collection."""

    def __init__(self, client: Any, collection: str) -> None:
        self._collection = client.collection(collection)

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

    async def list_expired(self, before: datetime) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self._collection.where(filter=FieldFilter("expires_at", "<=", before))
        snapshots = [snapshot async for snapshot in query.limit(100).stream()]
        return [
            snapshot.to_dict()
            for snapshot in snapshots
            if snapshot.to_dict().get("status") in {"COMPLETED", "FAILED"}
        ]

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for status in statuses:
            from google.cloud.firestore_v1.base_query import FieldFilter

            query = self._collection.where(filter=FieldFilter("status", "==", status))
            snapshots = [snapshot async for snapshot in query.limit(100).stream()]
            results.extend(snapshot.to_dict() for snapshot in snapshots)
        return results

    async def find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self._collection.where(filter=FieldFilter("idempotency_key", "==", key)).limit(1)
        async for snapshot in query.stream():
            payload = snapshot.to_dict()
            if payload.get("status") not in {"FAILED", "EXPIRED"}:
                return payload
        return None
