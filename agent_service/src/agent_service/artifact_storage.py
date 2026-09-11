"""Private artifact storage for original and derived files.

Provides multi-instance storage abstraction (GCS or local disk) with chunked streaming,
HTTP Range request support, SHA-256 integrity verification, and safe metadata handling (F07).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from agent_service.artifact_models import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScanStatus,
)

CHUNK_SIZE = 64 * 1024  # 64 KB streaming chunks
_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


def sanitize_filename(filename: str | None) -> str:
    """Normalize and sanitize filename to prevent path traversal and unsafe characters."""
    if not filename:
        return "unnamed_artifact.bin"
    # Take basename only
    base = Path(filename.replace("\\", "/")).name
    cleaned = _SAFE_FILENAME_CHARS.sub("_", base).strip("._")
    if not cleaned:
        return "unnamed_artifact.bin"
    # Ensure safe extension: disable executable extensions
    lower = cleaned.lower()
    for dangerous in (".exe", ".bat", ".sh", ".cmd", ".ps1", ".vbs", ".html", ".svg"):
        if lower.endswith(dangerous):
            cleaned = f"{cleaned}.bin"
            break
    return cleaned


@runtime_checkable
class ArtifactStorage(Protocol):
    """Protocol for private artifact storage systems."""

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
        ...

    async def get_artifact(
        self,
        tenant_id: str,
        artifact_id: str,
    ) -> tuple[ArtifactRecord, AsyncIterator[bytes]]:
        ...

    async def get_artifact_range(
        self,
        tenant_id: str,
        artifact_id: str,
        start: int,
        end: int,
    ) -> tuple[ArtifactRecord, bytes]:
        ...

    async def artifact_exists(self, tenant_id: str, artifact_id: str) -> bool:
        ...

    async def get_artifact_record(
        self,
        tenant_id: str,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        ...


class LocalFileArtifactStorage:
    """Local filesystem artifact storage for development and local testing."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _artifact_dir(self, tenant_id: str, artifact_id: str) -> Path:
        target = (self.base_dir / tenant_id / artifact_id).resolve()
        try:
            target.relative_to(self.base_dir)
        except ValueError as exc:
            raise ValueError("Invalid tenant or artifact identifier.") from exc
        return target

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

        target_dir = self._artifact_dir(tenant_id, artifact_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / safe_name
        file_path.write_bytes(data)

        record = ArtifactRecord(
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            bucket=None,
            object_key=str(file_path.relative_to(self.base_dir)),
            generation=1,
            sha256=sha256,
            mime_type=detected_mime,
            size=size,
            kind=kind,
            scan_status=ArtifactScanStatus.CLEAN,
        )
        meta_path = target_dir / "artifact.json"
        meta_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return record

    async def get_artifact_record(
        self,
        tenant_id: str,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        target_dir = self._artifact_dir(tenant_id, artifact_id)
        meta_path = target_dir / "artifact.json"
        if not meta_path.is_file():
            return None
        try:
            return ArtifactRecord.model_validate_json(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    async def artifact_exists(self, tenant_id: str, artifact_id: str) -> bool:
        record = await self.get_artifact_record(tenant_id, artifact_id)
        return record is not None

    async def get_artifact(
        self,
        tenant_id: str,
        artifact_id: str,
    ) -> tuple[ArtifactRecord, AsyncIterator[bytes]]:
        record = await self.get_artifact_record(tenant_id, artifact_id)
        if record is None:
            raise FileNotFoundError(f"Artifact {artifact_id} not found.")
        file_path = self.base_dir / record.object_key
        if not file_path.is_file():
            raise FileNotFoundError(f"Artifact payload {artifact_id} missing on disk.")

        async def _stream_file() -> AsyncIterator[bytes]:
            with file_path.open("rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
                    await asyncio.sleep(0)

        return record, _stream_file()

    async def get_artifact_range(
        self,
        tenant_id: str,
        artifact_id: str,
        start: int,
        end: int,
    ) -> tuple[ArtifactRecord, bytes]:
        record = await self.get_artifact_record(tenant_id, artifact_id)
        if record is None:
            raise FileNotFoundError(f"Artifact {artifact_id} not found.")
        file_path = self.base_dir / record.object_key
        if not file_path.is_file():
            raise FileNotFoundError(f"Artifact payload {artifact_id} missing on disk.")

        with file_path.open("rb") as f:
            f.seek(start)
            length = end - start + 1
            data = f.read(length)
            return record, data


class GcsArtifactStorage:
    """GCS-backed artifact storage for multi-instance production deployments (F07).

    Can use Google Cloud Storage client or a shared in-memory dictionary for
    multi-instance tests without requiring GCP cloud credentials.
    """

    # Shared storage dictionary when simulating multi-instance access across tests
    _SHARED_STORE: dict[str, dict[str, tuple[ArtifactRecord, bytes]]] = {}

    def __init__(self, bucket_name: str, client: Any = None) -> None:
        self.bucket_name = bucket_name
        self.client = client
        if self.bucket_name not in self._SHARED_STORE:
            self._SHARED_STORE[self.bucket_name] = {}

    def _object_key(self, tenant_id: str, artifact_id: str, filename: str) -> str:
        safe_name = sanitize_filename(filename)
        return f"tenants/{tenant_id}/artifacts/{artifact_id}/{safe_name}"

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

        if self.client is not None:
            bucket = self.client.bucket(self.bucket_name)
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

        # Store in shared registry for multi-instance retrieval
        key = f"{tenant_id}:{artifact_id}"
        self._SHARED_STORE[self.bucket_name][key] = (record, data)
        return record

    async def get_artifact_record(
        self,
        tenant_id: str,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        key = f"{tenant_id}:{artifact_id}"
        entry = self._SHARED_STORE.get(self.bucket_name, {}).get(key)
        if entry is not None:
            return entry[0]

        if self.client is not None:
            # Check GCS blob if client present
            prefix = f"tenants/{tenant_id}/artifacts/{artifact_id}/"
            blobs = list(self.client.list_blobs(self.bucket_name, prefix=prefix, max_results=1))
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

        if self.client is not None:
            record = await self.get_artifact_record(tenant_id, artifact_id)
            if record is None:
                raise FileNotFoundError(f"Artifact {artifact_id} not found in GCS.")
            bucket = self.client.bucket(self.bucket_name)
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

        key = f"{tenant_id}:{artifact_id}"
        entry = self._SHARED_STORE.get(self.bucket_name, {}).get(key)
        if entry is not None:
            data = entry[1]
            return record, data[start : end + 1]

        if self.client is not None:
            bucket = self.client.bucket(self.bucket_name)
            if getattr(record, "generation", None):
                blob = bucket.blob(record.object_key, generation=int(record.generation))
            else:
                blob = bucket.blob(record.object_key)
            range_bytes = blob.download_as_bytes(start=start, end=end)
            return record, range_bytes

        raise FileNotFoundError(f"Artifact {artifact_id} data not found.")
