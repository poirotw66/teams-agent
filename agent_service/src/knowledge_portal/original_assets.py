"""Private original-file storage for knowledge versions.

Local filesystem remains the portal working copy. When artifact storage is
configured (FILE or GCS), commit also dual-writes an immutable artifact record
so multi-instance preview/download can pin generation (F07).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from .draft_assets import normalize_upload_filename
from .settings import PortalSettings

_TOKEN_PATTERN = re.compile(r"^orig-[0-9a-f]{24}$")


def build_portal_artifact_storage(settings: PortalSettings) -> Any | None:
    """Build optional artifact storage for original-asset dual-write."""
    backend = (settings.artifact_storage_backend or "FILE").upper()
    if backend == "GCS":
        from agent_service.artifact_storage import GcsArtifactStorage, build_gcs_storage_client

        bucket = settings.artifact_gcs_bucket
        if not bucket:
            raise ValueError(
                "KNOWLEDGE_PORTAL_ARTIFACT_GCS_BUCKET (or AI_OPS_ARTIFACT_GCS_BUCKET) "
                "is required when artifact storage backend is GCS."
            )
        return GcsArtifactStorage(
            bucket_name=bucket,
            client=build_gcs_storage_client(),
            allow_memory_fallback=False,
        )
    if backend in {"FILE", "LOCAL"}:
        from agent_service.artifact_storage import LocalFileArtifactStorage

        base = settings.artifact_storage_path or (
            (settings.original_assets_dir or settings.data_dir / "portal_originals")
            / "artifacts"
        )
        return LocalFileArtifactStorage(base)
    if backend in {"NONE", "OFF", "DISABLED"}:
        return None
    raise ValueError(f"Unsupported portal artifact storage backend: {backend}")


class OriginalAssetStore:
    def __init__(
        self,
        settings: PortalSettings,
        *,
        artifact_storage: Any | None = None,
    ) -> None:
        self.root = (
            settings.original_assets_dir
            or (settings.data_dir / "portal_originals")
        ).expanduser().resolve()
        self.pending_root = self.root / "pending"
        self.versions_root = self.root / "versions"
        self._settings = settings
        if artifact_storage is not None:
            self._artifact_storage = artifact_storage
        else:
            try:
                self._artifact_storage = build_portal_artifact_storage(settings)
            except ValueError:
                self._artifact_storage = None

    def store_pending(
        self,
        payload: bytes,
        *,
        filename: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        safe_name = normalize_upload_filename(filename or "document.pdf")
        token = f"orig-{secrets.token_hex(12)}"
        pending_dir = self.pending_root / token
        pending_dir.mkdir(parents=True, exist_ok=False)
        (pending_dir / "payload").write_bytes(payload)
        metadata = {
            "token": token,
            "filename": safe_name,
            "actor_id": actor_id,
            "content_type": mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        (pending_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "original_asset_token": token,
            "original_asset_name": safe_name,
            "original_asset_sha256": metadata["sha256"],
            "original_asset_content_type": metadata["content_type"],
            "original_asset_size": metadata["size"],
        }

    def _pending_metadata(self, token: str) -> tuple[Path, dict[str, Any]]:
        if not _TOKEN_PATTERN.fullmatch(token):
            raise ValueError("Invalid original asset token.")
        pending_dir = (self.pending_root / token).resolve()
        try:
            pending_dir.relative_to(self.pending_root.resolve())
        except ValueError as exc:
            raise ValueError("Invalid original asset token.") from exc
        metadata_path = pending_dir / "metadata.json"
        payload_path = pending_dir / "payload"
        if not metadata_path.is_file() or not payload_path.is_file():
            raise ValueError("Original asset upload has expired or is unavailable.")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return pending_dir, metadata

    def _dual_write_artifact(
        self,
        *,
        document_id: str,
        version_id: str,
        filename: str,
        content_type: str,
        payload: bytes,
    ) -> str | None:
        if self._artifact_storage is None:
            return None
        from agent_service.artifact_models import ArtifactKind

        artifact_id = f"art-{document_id}-{version_id}"
        tenant_id = self._settings.default_tenant_id or "default"

        async def _store() -> str:
            record = await self._artifact_storage.store_artifact(
                tenant_id,
                artifact_id,
                payload,
                filename=filename,
                mime_type=content_type,
                kind=ArtifactKind.ORIGINAL,
            )
            return str(record.artifact_id)

        try:
            return asyncio.run(_store())
        except RuntimeError:
            # Nested event loop (e.g. already inside FastAPI request). Use a
            # dedicated loop instead of failing the local commit path.
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_store())
            finally:
                loop.close()

    def commit_pending(
        self,
        token: str,
        *,
        document_id: str,
        version_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        pending_dir, metadata = self._pending_metadata(token)
        if metadata.get("actor_id") and metadata["actor_id"] != actor_id:
            raise ValueError("Original asset belongs to another uploader.")
        target_dir = (self.versions_root / document_id / version_id).resolve()
        try:
            target_dir.relative_to(self.versions_root.resolve())
        except ValueError as exc:
            raise ValueError("Invalid document/version target.") from exc
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = normalize_upload_filename(str(metadata.get("filename") or "document.pdf"))
        payload_path = pending_dir / "payload"
        payload = payload_path.read_bytes()
        target = target_dir / filename
        target.write_bytes(payload)
        shutil.rmtree(pending_dir, ignore_errors=True)
        content_type = str(metadata.get("content_type") or "application/octet-stream")
        artifact_ref = self._dual_write_artifact(
            document_id=document_id,
            version_id=version_id,
            filename=filename,
            content_type=content_type,
            payload=payload,
        )
        return {
            "original_asset_name": filename,
            "original_asset_sha256": str(metadata.get("sha256") or ""),
            "original_asset_content_type": content_type,
            "original_asset_size": int(metadata.get("size") or target.stat().st_size),
            "original_artifact_ref": artifact_ref,
        }

    def discard_pending(self, token: str | None) -> None:
        """Remove an upload that cannot become a knowledge version."""

        if not token or not _TOKEN_PATTERN.fullmatch(token):
            return
        pending_dir = (self.pending_root / token).resolve()
        try:
            pending_dir.relative_to(self.pending_root.resolve())
        except ValueError:
            return
        shutil.rmtree(pending_dir, ignore_errors=True)

    def path_for_version(
        self,
        *,
        document_id: str,
        version_id: str,
        filename: str | None,
    ) -> Path | None:
        if not filename:
            return None
        safe_name = normalize_upload_filename(filename)
        version_dir = (self.versions_root / document_id / version_id).resolve()
        try:
            version_dir.relative_to(self.versions_root.resolve())
        except ValueError:
            return None
        target = version_dir / safe_name
        return target if target.is_file() else None

    def copy_to_release(self, release_dir: Path, *, version) -> bool:
        source = self.path_for_version(
            document_id=version.document_id,
            version_id=version.version_id,
            filename=version.original_asset_name,
        )
        if source is None:
            return False
        target_dir = release_dir / "original" / version.document_id / version.version_id
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_dir / source.name)
        return True

    def copy_version(
        self,
        *,
        document_id: str,
        source_version_id: str,
        target_version_id: str,
        filename: str | None,
    ) -> bool:
        source = self.path_for_version(
            document_id=document_id,
            version_id=source_version_id,
            filename=filename,
        )
        if source is None:
            return False
        target_dir = (self.versions_root / document_id / target_version_id).resolve()
        try:
            target_dir.relative_to(self.versions_root.resolve())
        except ValueError:
            return False
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_dir / source.name)
        return True

    def remove_version(self, *, document_id: str, version_id: str) -> None:
        target = (self.versions_root / document_id / version_id).resolve()
        try:
            target.relative_to(self.versions_root.resolve())
        except ValueError:
            return
        shutil.rmtree(target, ignore_errors=True)
