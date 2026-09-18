from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .asset_validation import (
    ALLOWED_IMAGE_SUFFIXES,
    _content_type,
    _copy_image_dir,
    asset_content_type,
    is_expected_asset_markdown_path,
    resolve_local_asset_path,
    validate_asset_bundle,
)
from .draft_markdown import (
    markdown_asset_ref,
    markdown_image_references,
    normalize_upload_filename,
    parse_markdown_import,
    referenced_asset_filenames,
    referenced_asset_relative_paths,
    rewrite_local_image_refs,
    slug_from_title,
    title_from_filename,
)
from .models import DraftAssetRecord
from .settings import PortalSettings

# Compatibility re-exports for portal modules that historically imported via draft_assets.
__all__ = [
    "ALLOWED_IMAGE_SUFFIXES",
    "DraftAssetStore",
    "asset_content_type",
    "is_expected_asset_markdown_path",
    "markdown_asset_ref",
    "markdown_image_references",
    "normalize_upload_filename",
    "parse_markdown_import",
    "referenced_asset_filenames",
    "referenced_asset_relative_paths",
    "resolve_local_asset_path",
    "rewrite_local_image_refs",
    "slug_from_title",
    "title_from_filename",
    "validate_asset_bundle",
]


@dataclass(frozen=True)
class DraftAssetStore:
    settings: PortalSettings
    storage_client: Any | None = None

    @property
    def root(self) -> Path:
        return self.settings.drafts_dir

    def bundle_dir(self, document_id: str, version_id: str) -> Path:
        return self.root / document_id / version_id

    def assets_root(self, document_id: str, version_id: str) -> Path:
        return self.bundle_dir(document_id, version_id) / "assets"

    def asset_dir(self, document_id: str, version_id: str, asset_slug: str) -> Path:
        return self.assets_root(document_id, version_id) / asset_slug

    def list_assets(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
    ) -> list[DraftAssetRecord]:
        bucket = self._gcs_bucket()
        if bucket is not None:
            return self._list_gcs_assets(bucket, document_id, version_id, asset_slug)
        directory = self.asset_dir(document_id, version_id, asset_slug)
        if not directory.is_dir():
            return []
        items: list[DraftAssetRecord] = []
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
                continue
            payload = path.read_bytes()
            items.append(
                DraftAssetRecord(
                    filename=path.name,
                    size_bytes=len(payload),
                    content_type=_content_type(path.suffix),
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
        return items

    def save_asset(
        self,
        *,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
        payload: bytes,
    ) -> DraftAssetRecord:
        if len(payload) > self.settings.max_asset_bytes:
            raise ValueError(f"Image exceeds {self.settings.max_asset_bytes} bytes: {filename}")
        normalized = normalize_upload_filename(filename)
        suffix = Path(normalized).suffix.lower()
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image type: {suffix or 'unknown'}")
        existing = self.list_assets(document_id, version_id, asset_slug)
        replacing = any(item.filename == normalized for item in existing)
        if not replacing and len(existing) >= self.settings.max_assets_per_version:
            raise ValueError(f"At most {self.settings.max_assets_per_version} images per draft.")
        target_dir = self.asset_dir(document_id, version_id, asset_slug)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / normalized
        target.write_bytes(payload)
        bucket = self._gcs_bucket()
        if bucket is not None:
            blob = bucket.blob(self._gcs_asset_key(document_id, version_id, asset_slug, normalized))
            blob.metadata = {"sha256": hashlib.sha256(payload).hexdigest()}
            blob.upload_from_string(payload, content_type=_content_type(suffix))
        return DraftAssetRecord(
            filename=normalized,
            size_bytes=len(payload),
            content_type=_content_type(suffix),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def delete_asset(
        self,
        *,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
    ) -> None:
        target = self.asset_dir(document_id, version_id, asset_slug) / normalize_upload_filename(
            filename
        )
        if target.exists():
            target.unlink()
        bucket = self._gcs_bucket()
        if bucket is not None:
            blob = bucket.blob(
                self._gcs_asset_key(
                    document_id,
                    version_id,
                    asset_slug,
                    normalize_upload_filename(filename),
                )
            )
            try:
                blob.delete()
            except Exception as error:  # noqa: BLE001 - external storage boundary
                if error.__class__.__name__ not in {"NotFound", "NotFoundError"}:
                    raise

    def copy_bundle(
        self,
        *,
        source_document_id: str,
        source_version_id: str,
        target_document_id: str,
        target_version_id: str,
        asset_slug: str,
    ) -> None:
        bucket = self._gcs_bucket()
        if bucket is not None:
            source_prefix = self._gcs_asset_prefix(
                source_document_id,
                source_version_id,
                asset_slug,
            )
            target_prefix = self._gcs_asset_prefix(
                target_document_id,
                target_version_id,
                asset_slug,
            )
            for blob in bucket.list_blobs(prefix=f"{source_prefix}/"):
                relative = blob.name.removeprefix(f"{source_prefix}/")
                if relative and Path(relative).suffix.lower() in ALLOWED_IMAGE_SUFFIXES:
                    bucket.copy_blob(blob, bucket, f"{target_prefix}/{relative}")
            self.materialize_bundle(target_document_id, target_version_id, asset_slug)
            return
        source_dir = self.asset_dir(source_document_id, source_version_id, asset_slug)
        if source_dir.is_dir():
            target_dir = self.asset_dir(target_document_id, target_version_id, asset_slug)
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            return
        legacy_dir = self.settings.data_dir / "assets" / asset_slug
        if legacy_dir.is_dir():
            target_dir = self.asset_dir(target_document_id, target_version_id, asset_slug)
            target_dir.mkdir(parents=True, exist_ok=True)
            for path in legacy_dir.iterdir():
                if path.is_file() and path.suffix.lower() in ALLOWED_IMAGE_SUFFIXES:
                    shutil.copy2(path, target_dir / path.name)

    def materialize_workspace(
        self,
        workspace_root: Path,
        *,
        version,
        source_filename: str,
    ) -> None:
        sources_dir = workspace_root / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        body = version.canonical_content
        target = sources_dir / source_filename
        target.write_text(body, encoding="utf-8")
        slug = version.asset_slug or slug_from_title(version.title)
        asset_dir = self.asset_dir(version.document_id, version.version_id, slug)
        if asset_dir.is_dir():
            release_assets = workspace_root / "assets" / slug
            release_assets.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(asset_dir, release_assets)
            return
        legacy_dir = self.settings.data_dir / "assets" / slug
        if legacy_dir.is_dir():
            release_assets = workspace_root / "assets" / slug
            release_assets.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(legacy_dir, release_assets)

    def copy_assets_to_release(
        self,
        release_dir: Path,
        *,
        version,
    ) -> None:
        slug = version.asset_slug or slug_from_title(version.title)
        target_dir = release_dir / "assets" / slug
        if self.materialize_bundle(version.document_id, version.version_id, slug):
            source_dir = self.asset_dir(version.document_id, version.version_id, slug)
            if _copy_image_dir(source_dir, target_dir):
                return
        source_dir = self.asset_dir(version.document_id, version.version_id, slug)
        if not _copy_image_dir(source_dir, target_dir):
            legacy_dir = self.settings.data_dir / "assets" / slug
            if not _copy_image_dir(legacy_dir, target_dir):
                _copy_image_dir(
                    self.settings.data_dir / "sources" / "assets" / slug,
                    target_dir,
                )
        self._supplement_corpus_assets(
            target_dir,
            slug,
            getattr(version, "canonical_content", ""),
        )
        self._copy_markdown_referenced_corpus_assets(
            release_dir / "assets",
            getattr(version, "canonical_content", ""),
        )

    def materialize_bundle(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
    ) -> bool:
        bucket = self._gcs_bucket()
        if bucket is None:
            return False
        target_dir = self.asset_dir(document_id, version_id, asset_slug)
        prefix = self._gcs_asset_prefix(document_id, version_id, asset_slug)
        downloaded = False
        for blob in bucket.list_blobs(prefix=f"{prefix}/"):
            filename = normalize_upload_filename(Path(blob.name).name)
            if Path(filename).suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(target_dir / filename))
            downloaded = True
        return downloaded

    def read_asset_bytes(
        self,
        *,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
    ) -> tuple[bytes, str]:
        normalized = normalize_upload_filename(filename)
        suffix = Path(normalized).suffix.lower()
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise ValueError("Unsupported image type.")
        bucket = self._gcs_bucket()
        if bucket is not None:
            blob = bucket.blob(self._gcs_asset_key(document_id, version_id, asset_slug, normalized))
            try:
                return blob.download_as_bytes(), asset_content_type(suffix)
            except Exception as error:  # noqa: BLE001 - external storage boundary
                raise FileNotFoundError(normalized) from error
        path = self.asset_dir(document_id, version_id, asset_slug) / normalized
        if not path.is_file():
            raise FileNotFoundError(normalized)
        return path.read_bytes(), asset_content_type(suffix)

    def _gcs_bucket(self) -> Any | None:
        if (
            self.settings.artifact_storage_backend.upper() != "GCS"
            or not self.settings.artifact_gcs_bucket
        ):
            return None
        if self.storage_client is not None:
            return self.storage_client.bucket(self.settings.artifact_gcs_bucket)
        try:
            from google.cloud import storage
        except ImportError as error:  # pragma: no cover - optional deployment dependency
            raise RuntimeError(
                "google-cloud-storage is required for shared draft assets."
            ) from error
        return storage.Client().bucket(self.settings.artifact_gcs_bucket)

    def _gcs_asset_prefix(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
    ) -> str:
        for value in (document_id, version_id):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
                raise ValueError("Invalid document asset identifier.")
        slug = slug_from_title(asset_slug)
        return (
            f"portal-drafts/{self.settings.default_tenant_id}/documents/"
            f"{document_id}/versions/{version_id}/assets/{slug}"
        )

    def _gcs_asset_key(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
    ) -> str:
        return (
            f"{self._gcs_asset_prefix(document_id, version_id, asset_slug)}/"
            f"{normalize_upload_filename(filename)}"
        )

    def _list_gcs_assets(
        self,
        bucket: Any,
        document_id: str,
        version_id: str,
        asset_slug: str,
    ) -> list[DraftAssetRecord]:
        prefix = self._gcs_asset_prefix(document_id, version_id, asset_slug)
        items: list[DraftAssetRecord] = []
        for blob in bucket.list_blobs(prefix=f"{prefix}/"):
            filename = Path(blob.name).name
            suffix = Path(filename).suffix.lower()
            if suffix not in ALLOWED_IMAGE_SUFFIXES:
                continue
            metadata = getattr(blob, "metadata", None) or {}
            items.append(
                DraftAssetRecord(
                    filename=filename,
                    size_bytes=int(getattr(blob, "size", 0) or 0),
                    content_type=str(
                        getattr(blob, "content_type", None) or asset_content_type(suffix)
                    ),
                    sha256=str(metadata.get("sha256") or ""),
                )
            )
        return sorted(items, key=lambda item: item.filename)

    def _supplement_corpus_assets(
        self,
        target_dir: Path,
        slug: str,
        markdown_content: str,
    ) -> None:
        corpus_dir = self.settings.data_dir / "sources" / "assets" / slug
        if not corpus_dir.is_dir() or not markdown_content:
            return
        for filename in referenced_asset_filenames(markdown_content, slug):
            destination = target_dir / filename
            source = corpus_dir / filename
            if destination.is_file() or not source.is_file():
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def _copy_markdown_referenced_corpus_assets(
        self,
        release_assets_root: Path,
        markdown_content: str,
    ) -> None:
        """Copy corpus images using the folder path cited in markdown.

        Historical corpus folders (e.g. ``國金CRM_OTP綁訂操作``) can diverge from
        ``slug_from_title`` (e.g. ``國金 CRM OTP 綁訂操作``). Delivery URLs follow
        the markdown path, so packaging must materialize that exact relative path.
        """
        if not markdown_content:
            return
        corpus_root = self.settings.data_dir / "sources" / "assets"
        for relative in referenced_asset_relative_paths(markdown_content):
            destination = release_assets_root / relative
            if destination.is_file():
                continue
            source = corpus_root / relative
            if not source.is_file():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def next_filename(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
    ) -> str:
        existing = {item.filename for item in self.list_assets(document_id, version_id, asset_slug)}
        index = 1
        while True:
            candidate = f"p{index:02d}.png"
            if candidate not in existing:
                return candidate
            index += 1

