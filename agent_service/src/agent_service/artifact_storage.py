"""Private artifact storage for original and derived files.

Protocol and local-file storage live in ``knowledge_core``. This module keeps
the GCS implementation and client factory used by Agent/Backoffice/composition.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from knowledge_core.artifact_models import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScanStatus,
)
from knowledge_core.artifact_ports import (
    CHUNK_SIZE,
    ArtifactStorage,
    LocalFileArtifactStorage,
    sanitize_filename,
)

__all__ = [
    "CHUNK_SIZE",
    "ArtifactStorage",
    "GcsArtifactStorage",
    "LocalFileArtifactStorage",
    "build_gcs_storage_client",
    "sanitize_filename",
]


def build_gcs_storage_client() -> Any:
    """Create a real Google Cloud Storage client for formal GCS mode."""
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - optional deployment dependency
        raise RuntimeError(
            "google-cloud-storage is required for GCS artifact storage."
        ) from exc
    return storage.Client()


class GcsArtifactStorage:
    """GCS-backed artifact storage for multi-instance production deployments (F07).

    Formal mode requires a real GCS client. The in-memory ``_SHARED_STORE`` is
    only allowed when ``allow_memory_fallback=True`` (unit tests).
    """

    # Shared storage dictionary when simulating multi-instance access across tests
    _SHARED_STORE: ClassVar[dict[str, dict[str, tuple[ArtifactRecord, bytes]]]] = {}

    def __init__(
        self,
        bucket_name: str,
        client: Any = None,
        *,
        allow_memory_fallback: bool = False,
    ) -> None:
        self.bucket_name = bucket_name
        self.client = client
        self._allow_memory_fallback = bool(allow_memory_fallback)
        if self.client is None and not self._allow_memory_fallback:
            raise ValueError(
                "GcsArtifactStorage requires a real GCS client in formal mode. "
                "Pass client=build_gcs_storage_client() or allow_memory_fallback=True for tests."
            )
        if self.bucket_name not in self._SHARED_STORE:
            self._SHARED_STORE[self.bucket_name] = {}

    def _object_key(self, tenant_id: str, artifact_id: str, filename: str) -> str:
        safe_name = sanitize_filename(filename)
        return f"tenants/{tenant_id}/artifacts/{artifact_id}/{safe_name}"

    def _require_client_for_cloud(self) -> Any:
        if self.client is not None:
            return self.client
        if self._allow_memory_fallback:
            return None
        raise RuntimeError("GCS client missing; memory fallback is disabled in formal mode.")

    async def store_artifact(
        self,
        tenant_id: str,
        artifact_id: str,
        data: bytes,
        *,
        filename: str,
        mime_type: str | None = None,
        kind: ArtifactKind = ArtifactKind.ORIGINAL,
    ) -> ArtifactRecord:
        safe_name = sanitize_filename(filename)
        detected_mime = (
            mime_type
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )
        sha256 = hashlib.sha256(data).hexdigest()
        size = len(data)
        object_key = self._object_key(tenant_id, artifact_id, safe_name)
        client = self._require_client_for_cloud()

        if client is not None:
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(object_key)
            blob.metadata = {"sha256": sha256}
            blob.upload_from_string(data, content_type=detected_mime)
            generation = blob.generation or 1
        else:
            generation = 1

        record = ArtifactRecord(
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            bucket=self.bucket_name,
            object_key=object_key,
            generation=generation,
            sha256=sha256,
            mime_type=detected_mime,
            size=size,
            kind=kind,
            scan_status=ArtifactScanStatus.CLEAN,
        )

        if self._allow_memory_fallback or client is None:
            key = f"{tenant_id}:{artifact_id}"
            self._SHARED_STORE[self.bucket_name][key] = (record, data)
        return record

    async def get_artifact_record(
        self,
        tenant_id: str,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        key = f"{tenant_id}:{artifact_id}"
        if self._allow_memory_fallback:
            entry = self._SHARED_STORE.get(self.bucket_name, {}).get(key)
            if entry is not None:
                return entry[0]

        client = self._require_client_for_cloud()
        if client is not None:
            # Check GCS blob if client present
            prefix = f"tenants/{tenant_id}/artifacts/{artifact_id}/"
            blobs = list(client.list_blobs(self.bucket_name, prefix=prefix, max_results=1))
            if blobs:
                blob = blobs[0]
                blob_sha256 = (blob.metadata or {}).get("sha256") or ""
                record = ArtifactRecord(
                    artifact_id=artifact_id,
                    tenant_id=tenant_id,
                    bucket=self.bucket_name,
                    object_key=blob.name,
                    generation=blob.generation or 1,
                    sha256=blob_sha256,
                    mime_type=blob.content_type or "application/octet-stream",
                    size=blob.size or 0,
                )
                return record
        return None

    async def artifact_exists(self, tenant_id: str, artifact_id: str) -> bool:
        record = await self.get_artifact_record(tenant_id, artifact_id)
        return record is not None

    async def get_artifact(
        self,
        tenant_id: str,
        artifact_id: str,
    ) -> tuple[ArtifactRecord, AsyncIterator[bytes]]:
        key = f"{tenant_id}:{artifact_id}"
        if self._allow_memory_fallback:
            entry = self._SHARED_STORE.get(self.bucket_name, {}).get(key)
            if entry is not None:
                record, data = entry

                async def _stream_data() -> AsyncIterator[bytes]:
                    offset = 0
                    while offset < len(data):
                        chunk = data[offset : offset + CHUNK_SIZE]
                        offset += len(chunk)
                        yield chunk
                        await asyncio.sleep(0)

                return record, _stream_data()

        client = self._require_client_for_cloud()
        if client is not None:
            record = await self.get_artifact_record(tenant_id, artifact_id)
            if record is None:
                raise FileNotFoundError(f"Artifact {artifact_id} not found in GCS.")
            bucket = client.bucket(self.bucket_name)
            # Pin immutable generation when available (F07).
            if getattr(record, "generation", None):
                blob = bucket.blob(record.object_key, generation=int(record.generation))
            else:
                blob = bucket.blob(record.object_key)

            async def _stream_gcs_blob() -> AsyncIterator[bytes]:
                with blob.open("rb") as f:
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        yield chunk
                        await asyncio.sleep(0)

            return record, _stream_gcs_blob()

        raise FileNotFoundError(f"Artifact {artifact_id} not found in GCS.")

    async def get_artifact_range(
        self,
        tenant_id: str,
        artifact_id: str,
        start: int,
        end: int,
    ) -> tuple[ArtifactRecord, bytes]:
        record = await self.get_artifact_record(tenant_id, artifact_id)
        if record is None:
            raise FileNotFoundError(f"Artifact {artifact_id} not found in GCS.")

        if self._allow_memory_fallback:
            key = f"{tenant_id}:{artifact_id}"
            entry = self._SHARED_STORE.get(self.bucket_name, {}).get(key)
            if entry is not None:
                data = entry[1]
                return record, data[start : end + 1]

        client = self._require_client_for_cloud()
        if client is not None:
            bucket = client.bucket(self.bucket_name)
            if getattr(record, "generation", None):
                blob = bucket.blob(record.object_key, generation=int(record.generation))
            else:
                blob = bucket.blob(record.object_key)
            range_bytes = blob.download_as_bytes(start=start, end=end)
            return record, range_bytes

        raise FileNotFoundError(f"Artifact {artifact_id} data not found.")
