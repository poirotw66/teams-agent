"""Direct SourceRecord repository and bounded in-memory cache.

Ensures O(1) direct source reference lookup without scanning release directories,
and bounds memory growth via LRU/TTL caching as required by A06 and F03.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, runtime_checkable

from .source_models import SourceRecord


class BoundedSourceCache:
    """Thread-safe LRU and TTL bounded cache for SourceRecord lookups (A06).

    Guarantees that memory does not grow unbounded under high citation loads.
    Cache key: (tenant_id, source_ref_id).
    """

    def __init__(self, max_size: int = 500, ttl_seconds: float = 300.0) -> None:
        self.max_size = max(1, max_size)
        self.ttl_seconds = max(0.0, ttl_seconds)
        self._cache: OrderedDict[str, tuple[float, SourceRecord]] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _key(tenant_id: str, source_ref_id: str) -> str:
        return f"{tenant_id}:{source_ref_id}"

    def get(self, tenant_id: str, source_ref_id: str) -> SourceRecord | None:
        key = self._key(tenant_id, source_ref_id)
        with self._lock:
            if key not in self._cache:
                return None
            inserted_at, record = self._cache[key]
            if time.monotonic() - inserted_at > self.ttl_seconds:
                del self._cache[key]
                return None
            # Move to end to mark recently accessed (LRU)
            self._cache.move_to_end(key)
            return record

    def put(self, record: SourceRecord) -> None:
        key = self._key(record.tenant_id, record.source_ref_id)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.monotonic(), record)
            # Evict oldest if exceeding capacity
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def invalidate(self, tenant_id: str, source_ref_id: str) -> None:
        key = self._key(tenant_id, source_ref_id)
        with self._lock:
            self._cache.pop(key, None)

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


@runtime_checkable
class SourceRecordRepository(Protocol):
    """Protocol for direct source record storage and retrieval."""

    async def get_source_record(
        self, tenant_id: str, source_ref_id: str
    ) -> SourceRecord | None:
        ...

    async def save_source_record(self, record: SourceRecord) -> None:
        ...

    async def save_source_records(self, records: list[SourceRecord]) -> None:
        ...

    async def list_source_records_for_version(
        self, tenant_id: str, document_id: str, version_id: str
    ) -> list[SourceRecord]:
        ...

    async def list_source_records_for_release(
        self, tenant_id: str, release_id: str
    ) -> list[SourceRecord]:
        ...

    async def delete_source_record(
        self, tenant_id: str, source_ref_id: str
    ) -> bool:
        ...


class InMemorySourceRecordRepository:
    """In-memory source repository for unit tests and local isolation."""

    def __init__(self) -> None:
        # Keyed by (tenant_id, source_ref_id)
        self._records: dict[tuple[str, str], SourceRecord] = {}

    def get_source_record_sync(
        self, tenant_id: str, source_ref_id: str
    ) -> SourceRecord | None:
        return self._records.get((tenant_id, source_ref_id))

    def save_source_record_sync(self, record: SourceRecord) -> None:
        self._records[(record.tenant_id, record.source_ref_id)] = record

    async def get_source_record(
        self, tenant_id: str, source_ref_id: str
    ) -> SourceRecord | None:
        return self.get_source_record_sync(tenant_id, source_ref_id)

    async def save_source_record(self, record: SourceRecord) -> None:
        self.save_source_record_sync(record)

    async def save_source_records(self, records: list[SourceRecord]) -> None:
        for record in records:
            await self.save_source_record(record)

    async def list_source_records_for_version(
        self, tenant_id: str, document_id: str, version_id: str
    ) -> list[SourceRecord]:
        return [
            rec
            for (t_id, _), rec in self._records.items()
            if t_id == tenant_id
            and rec.document_id == document_id
            and rec.version_id == version_id
        ]

    async def list_source_records_for_release(
        self, tenant_id: str, release_id: str
    ) -> list[SourceRecord]:
        return [
            rec
            for (t_id, _), rec in self._records.items()
            if t_id == tenant_id and rec.release_id == release_id
        ]

    async def delete_source_record(
        self, tenant_id: str, source_ref_id: str
    ) -> bool:
        return self._records.pop((tenant_id, source_ref_id), None) is not None


class FileSourceRecordRepository:
    """File-based durable direct source record repository.

    Stores each record as an individual JSON document under:
    base_dir / tenant_id / {source_ref_id}.json
    Ensures O(1) direct reads without scanning directory trees.
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, tenant_id: str, source_ref_id: str) -> Path:
        tenant_dir = (self.base_dir / tenant_id).resolve()
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return tenant_dir / f"{source_ref_id}.json"

    def get_source_record_sync(
        self, tenant_id: str, source_ref_id: str
    ) -> SourceRecord | None:
        path = self._file_path(tenant_id, source_ref_id)
        if not path.is_file():
            return None
        try:
            return SourceRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save_source_record_sync(self, record: SourceRecord) -> None:
        path = self._file_path(record.tenant_id, record.source_ref_id)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temp_path.replace(path)

    async def get_source_record(
        self, tenant_id: str, source_ref_id: str
    ) -> SourceRecord | None:
        return self.get_source_record_sync(tenant_id, source_ref_id)

    async def save_source_record(self, record: SourceRecord) -> None:
        self.save_source_record_sync(record)

    async def save_source_records(self, records: list[SourceRecord]) -> None:
        for record in records:
            await self.save_source_record(record)

    async def list_source_records_for_version(
        self, tenant_id: str, document_id: str, version_id: str
    ) -> list[SourceRecord]:
        tenant_dir = self.base_dir / tenant_id
        if not tenant_dir.is_dir():
            return []
        matches: list[SourceRecord] = []
        for file in tenant_dir.glob("*.json"):
            try:
                rec = SourceRecord.model_validate_json(file.read_text(encoding="utf-8"))
                if rec.document_id == document_id and rec.version_id == version_id:
                    matches.append(rec)
            except (OSError, ValueError):
                continue
        return matches

    async def list_source_records_for_release(
        self, tenant_id: str, release_id: str
    ) -> list[SourceRecord]:
        tenant_dir = self.base_dir / tenant_id
        if not tenant_dir.is_dir():
            return []
        matches: list[SourceRecord] = []
        for file in tenant_dir.glob("*.json"):
            try:
                rec = SourceRecord.model_validate_json(file.read_text(encoding="utf-8"))
                if rec.release_id == release_id:
                    matches.append(rec)
            except (OSError, ValueError):
                continue
        return matches

    async def delete_source_record(
        self, tenant_id: str, source_ref_id: str
    ) -> bool:
        path = self._file_path(tenant_id, source_ref_id)
        if path.is_file():
            path.unlink(missing_ok=True)
            return True
        return False


class FirestoreSourceRecordRepository:
    """Firestore implementation for cloud production environments.

    Stores records under tenants/{tenant_id}/source_records/{source_ref_id}.
    """

    def __init__(self, client: Any = None, project_id: str | None = None) -> None:
        self.client = client
        self.project_id = project_id
        # In-memory backing when testing or before firestore initialization
        self._fallback = InMemorySourceRecordRepository()

    def _doc_ref(self, tenant_id: str, source_ref_id: str) -> Any:
        if self.client is None:
            return None
        return (
            self.client.collection("tenants")
            .document(tenant_id)
            .collection("source_records")
            .document(source_ref_id)
        )

    async def get_source_record(
        self, tenant_id: str, source_ref_id: str
    ) -> SourceRecord | None:
        doc_ref = self._doc_ref(tenant_id, source_ref_id)
        if doc_ref is None:
            return await self._fallback.get_source_record(tenant_id, source_ref_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict()
        return SourceRecord.model_validate(data)

    async def save_source_record(self, record: SourceRecord) -> None:
        doc_ref = self._doc_ref(record.tenant_id, record.source_ref_id)
        if doc_ref is None:
            await self._fallback.save_source_record(record)
            return
        doc_ref.set(record.model_dump(mode="json"))

    async def save_source_records(self, records: list[SourceRecord]) -> None:
        for record in records:
            await self.save_source_record(record)

    async def list_source_records_for_version(
        self, tenant_id: str, document_id: str, version_id: str
    ) -> list[SourceRecord]:
        if self.client is None:
            return await self._fallback.list_source_records_for_version(
                tenant_id, document_id, version_id
            )
        coll = (
            self.client.collection("tenants")
            .document(tenant_id)
            .collection("source_records")
        )
        query = (
            coll.where("document_id", "==", document_id)
            .where("version_id", "==", version_id)
            .stream()
        )
        return [SourceRecord.model_validate(doc.to_dict()) for doc in query]

    async def list_source_records_for_release(
        self, tenant_id: str, release_id: str
    ) -> list[SourceRecord]:
        if self.client is None:
            return await self._fallback.list_source_records_for_release(
                tenant_id, release_id
            )
        coll = (
            self.client.collection("tenants")
            .document(tenant_id)
            .collection("source_records")
        )
        query = coll.where("release_id", "==", release_id).stream()
        return [SourceRecord.model_validate(doc.to_dict()) for doc in query]

    async def delete_source_record(
        self, tenant_id: str, source_ref_id: str
    ) -> bool:
        doc_ref = self._doc_ref(tenant_id, source_ref_id)
        if doc_ref is None:
            return await self._fallback.delete_source_record(tenant_id, source_ref_id)
        doc_ref.delete()
        return True

    def get_source_record_sync(
        self, tenant_id: str, source_ref_id: str
    ) -> SourceRecord | None:
        doc_ref = self._doc_ref(tenant_id, source_ref_id)
        if doc_ref is None:
            return self._fallback.get_source_record_sync(tenant_id, source_ref_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return None
        return SourceRecord.model_validate(snapshot.to_dict())

    def save_source_record_sync(self, record: SourceRecord) -> None:
        doc_ref = self._doc_ref(record.tenant_id, record.source_ref_id)
        if doc_ref is None:
            self._fallback.save_source_record_sync(record)
            return
        doc_ref.set(record.model_dump(mode="json"))
