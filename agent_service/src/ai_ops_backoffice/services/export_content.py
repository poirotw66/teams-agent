"""Artifact storage is separate from durable export-job metadata."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class ExportContentStore(Protocol):
    async def put(self, *, job_id: str, content: bytes, content_type: str) -> str: ...
    async def get(self, *, content_ref: str) -> bytes | None: ...
    async def delete(self, *, content_ref: str) -> None: ...


class FileExportContentStore:
    """Local-only artifact store; not suitable for multi-instance deployment."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, content_ref: str) -> Path:
        candidate = (self._root / content_ref).resolve()
        if candidate.parent != self._root.resolve() or candidate.name != content_ref:
            raise ValueError("Invalid export content reference.")
        return candidate

    async def put(self, *, job_id: str, content: bytes, content_type: str) -> str:
        _ = content_type
        content_ref = f"{job_id}.artifact"
        target = self._path(content_ref)
        temporary = target.with_suffix(".tmp")
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return content_ref

    async def get(self, *, content_ref: str) -> bytes | None:
        path = self._path(content_ref)
        return path.read_bytes() if path.is_file() else None

    async def delete(self, *, content_ref: str) -> None:
        self._path(content_ref).unlink(missing_ok=True)


class MemoryExportContentStore:
    """Test-only content store.  Factory never selects this for deployment."""

    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}

    async def put(self, *, job_id: str, content: bytes, content_type: str) -> str:
        _ = content_type
        content_ref = f"memory:{job_id}"
        self.items[content_ref] = bytes(content)
        return content_ref

    async def get(self, *, content_ref: str) -> bytes | None:
        return self.items.get(content_ref)

    async def delete(self, *, content_ref: str) -> None:
        self.items.pop(content_ref, None)


class GcsExportContentStore:
    """Production artifact backend.  No bucket is contacted during construction."""

    def __init__(self, *, bucket_name: str, prefix: str = "ai-ops-exports") -> None:
        self._bucket_name = bucket_name
        self._prefix = prefix.strip("/")
        self._client = None

    def _bucket(self):
        if self._client is None:
            try:
                from google.cloud import storage
            except ImportError as exc:  # pragma: no cover - optional runtime dependency
                raise RuntimeError("GCS export content requires google-cloud-storage.") from exc
            self._client = storage.Client()
        return self._client.bucket(self._bucket_name)

    def _name(self, content_ref: str) -> str:
        if not content_ref.startswith(f"{self._prefix}/") or ".." in content_ref:
            raise ValueError("Invalid export content reference.")
        return content_ref

    async def put(self, *, job_id: str, content: bytes, content_type: str) -> str:
        content_ref = f"{self._prefix}/{job_id}.artifact"
        self._bucket().blob(content_ref).upload_from_string(content, content_type=content_type)
        return content_ref

    async def get(self, *, content_ref: str) -> bytes | None:
        blob = self._bucket().blob(self._name(content_ref))
        return None if not blob.exists() else blob.download_as_bytes()

    async def delete(self, *, content_ref: str) -> None:
        self._bucket().blob(self._name(content_ref)).delete()
