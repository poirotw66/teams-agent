"""Artifact storage protocol and local-file implementation.

GCS-backed storage stays in Agent runtime; Portal and Backoffice depend on this
protocol (and optional local storage) without importing Agent infra helpers.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from knowledge_core.artifact_models import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScanStatus,
)

__all__ = [
    "CHUNK_SIZE",
    "ArtifactStorage",
    "LocalFileArtifactStorage",
    "sanitize_filename",
]

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
