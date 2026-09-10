"""Private original-file storage for knowledge versions.

This local implementation mirrors the boundary expected from a future GCS
backend: callers receive an opaque pending token, while only the portal and
release publisher can resolve the private file.
"""

from __future__ import annotations

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


class OriginalAssetStore:
    def __init__(self, settings: PortalSettings) -> None:
        self.root = (
            settings.original_assets_dir
            or (settings.data_dir / "portal_originals")
        ).expanduser().resolve()
        self.pending_root = self.root / "pending"
        self.versions_root = self.root / "versions"

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
        target = target_dir / filename
        shutil.move(str(pending_dir / "payload"), target)
        shutil.rmtree(pending_dir, ignore_errors=True)
        return {
            "original_asset_name": filename,
            "original_asset_sha256": str(metadata.get("sha256") or ""),
            "original_asset_content_type": str(
                metadata.get("content_type") or "application/octet-stream"
            ),
            "original_asset_size": int(metadata.get("size") or target.stat().st_size),
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
