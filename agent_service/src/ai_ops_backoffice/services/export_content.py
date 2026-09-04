"""Artifact storage is separate from durable export-job metadata."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Protocol

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9._-]+")


def attempt_content_ref(
    *,
    job_id: str,
    attempt: int | None = None,
    lease_token: str | None = None,
    prefix: str = "",
) -> str:
    """Build an attempt/lease-scoped artifact name to avoid cross-owner clobber."""
    safe_job = _SAFE_TOKEN.sub("_", job_id)
    attempt_part = f"a{int(attempt)}" if attempt is not None else "a0"
    token_part = _SAFE_TOKEN.sub("", (lease_token or "none")[:12]) or "none"
    name = f"{safe_job}.{attempt_part}.{token_part}.artifact"
    if prefix:
        return f"{prefix.rstrip('/')}/{name}"
    return name


class ExportContentStore(Protocol):
    async def put(
        self,
        *,
        job_id: str,
        content: bytes,
        content_type: str,
        attempt: int | None = None,
        lease_token: str | None = None,
    ) -> str: ...

    async def get(self, *, content_ref: str) -> bytes | None: ...

    async def delete(self, *, content_ref: str) -> None: ...

    async def list_refs(self) -> list[str]: ...

    async def created_at_epoch(self, content_ref: str) -> float | None:
        """Return artifact creation time as unix epoch, or ``None`` if unknown."""
        ...


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

    async def put(
        self,
        *,
        job_id: str,
        content: bytes,
        content_type: str,
        attempt: int | None = None,
        lease_token: str | None = None,
    ) -> str:
        _ = content_type
        content_ref = attempt_content_ref(
            job_id=job_id, attempt=attempt, lease_token=lease_token
        )
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

    async def list_refs(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(
            path.name
            for path in self._root.iterdir()
            if path.is_file() and path.name.endswith(".artifact")
        )

    async def created_at_epoch(self, content_ref: str) -> float | None:
        try:
            return self._path(content_ref).stat().st_mtime
        except OSError:
            return None


class MemoryExportContentStore:
    """Test-only content store.  Factory never selects this for deployment."""

    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}
        self.created_at: dict[str, float] = {}

    async def put(
        self,
        *,
        job_id: str,
        content: bytes,
        content_type: str,
        attempt: int | None = None,
        lease_token: str | None = None,
    ) -> str:
        _ = content_type
        content_ref = "memory:" + attempt_content_ref(
            job_id=job_id, attempt=attempt, lease_token=lease_token
        )
        self.items[content_ref] = bytes(content)
        self.created_at[content_ref] = time.time()
        return content_ref

    async def get(self, *, content_ref: str) -> bytes | None:
        return self.items.get(content_ref)

    async def delete(self, *, content_ref: str) -> None:
        self.items.pop(content_ref, None)
        self.created_at.pop(content_ref, None)

    async def list_refs(self) -> list[str]:
        return sorted(self.items)

    async def created_at_epoch(self, content_ref: str) -> float | None:
        return self.created_at.get(content_ref)


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

    async def put(
        self,
        *,
        job_id: str,
        content: bytes,
        content_type: str,
        attempt: int | None = None,
        lease_token: str | None = None,
    ) -> str:
        content_ref = attempt_content_ref(
            job_id=job_id,
            attempt=attempt,
            lease_token=lease_token,
            prefix=self._prefix,
        )
        self._bucket().blob(content_ref).upload_from_string(content, content_type=content_type)
        return content_ref

    async def get(self, *, content_ref: str) -> bytes | None:
        blob = self._bucket().blob(self._name(content_ref))
        return None if not blob.exists() else blob.download_as_bytes()

    async def delete(self, *, content_ref: str) -> None:
        self._bucket().blob(self._name(content_ref)).delete()

    async def list_refs(self) -> list[str]:
        blobs = self._bucket().list_blobs(prefix=f"{self._prefix}/")
        return sorted(
            blob.name
            for blob in blobs
            if blob.name.endswith(".artifact")
        )

    async def created_at_epoch(self, content_ref: str) -> float | None:
        blob = self._bucket().blob(self._name(content_ref))
        try:
            blob.reload()
        except Exception:  # noqa: BLE001
            return None
        created = getattr(blob, "time_created", None) or getattr(blob, "updated", None)
        if created is None:
            return None
        return float(created.timestamp())
