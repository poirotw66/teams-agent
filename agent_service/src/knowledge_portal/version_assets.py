from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from knowledge_core.artifacts import INDEX_RELATIVE_PATH

from .draft_assets import (
    ALLOWED_IMAGE_SUFFIXES,
    DraftAssetStore,
    asset_content_type,
    is_expected_asset_markdown_path,
    markdown_image_references,
    normalize_upload_filename,
    slug_from_title,
)
from .models import ChunkPreviewImage, KnowledgeVersionRecord, ReleaseRecord
from .settings import PortalSettings


@dataclass(frozen=True)
class VersionAssetContext:
    version: KnowledgeVersionRecord
    release: ReleaseRecord | None
    allowed_paths: frozenset[str]

    @property
    def release_id(self) -> str | None:
        return self.release.release_id if self.release else None


async def build_version_asset_context(
    settings: PortalSettings,
    *,
    version: KnowledgeVersionRecord,
    release: ReleaseRecord | None,
) -> VersionAssetContext:
    if release is None:
        store = DraftAssetStore(settings)
        slug = version.asset_slug or slug_from_title(version.title)
        records = await asyncio.to_thread(
            store.list_assets,
            version.document_id,
            version.version_id,
            slug,
        )
        paths = {f"{slug}/{record.filename}" for record in records}
    else:
        paths = await _published_image_paths(
            settings,
            release=release,
            document_id=version.document_id,
            version_id=version.version_id,
        )
    return VersionAssetContext(
        version=version,
        release=release,
        allowed_paths=frozenset(paths),
    )


def images_for_chunk(
    content: str,
    *,
    context: VersionAssetContext,
) -> list[ChunkPreviewImage]:
    slug = context.version.asset_slug or slug_from_title(context.version.title)
    images: list[ChunkPreviewImage] = []
    seen: set[str] = set()
    for alt_text, target in markdown_image_references(content):
        filename = _referenced_filename(target, asset_slug=slug)
        if filename is None:
            continue
        indexed_path = f"{slug}/{filename}"
        if indexed_path not in context.allowed_paths or indexed_path in seen:
            continue
        seen.add(indexed_path)
        url = (
            f"/api/knowledge/v1/documents/{quote(context.version.document_id, safe='')}"
            f"/versions/{quote(context.version.version_id, safe='')}"
            f"/assets/{quote(filename, safe='')}"
        )
        images.append(
            ChunkPreviewImage(
                path=target,
                filename=filename,
                alt_text=alt_text or Path(filename).stem,
                content_type=asset_content_type(Path(filename).suffix),
                url=url,
            )
        )
    return images


async def read_version_asset(
    settings: PortalSettings,
    *,
    context: VersionAssetContext,
    filename: str,
) -> tuple[bytes, str]:
    normalized = normalize_upload_filename(filename)
    suffix = Path(normalized).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise FileNotFoundError(normalized)
    slug = context.version.asset_slug or slug_from_title(context.version.title)
    if f"{slug}/{normalized}" not in context.allowed_paths:
        raise FileNotFoundError(normalized)
    if context.release is None:
        return await asyncio.to_thread(
            DraftAssetStore(settings).read_asset_bytes,
            document_id=context.version.document_id,
            version_id=context.version.version_id,
            asset_slug=slug,
            filename=normalized,
        )
    return await asyncio.to_thread(
        _read_published_asset,
        settings,
        context.release,
        slug,
        normalized,
    )


def _referenced_filename(target: str, *, asset_slug: str) -> str | None:
    if "://" in target or target.startswith(("data:", "/", "\\")):
        return None
    filename = Path(target.replace("\\", "/")).name
    try:
        normalized = normalize_upload_filename(filename)
    except ValueError:
        return None
    if not is_expected_asset_markdown_path(
        target,
        asset_slug=asset_slug,
        filename=normalized,
    ):
        return None
    return normalized


async def _published_image_paths(
    settings: PortalSettings,
    *,
    release: ReleaseRecord,
    document_id: str,
    version_id: str,
) -> set[str]:
    payload = await asyncio.to_thread(_read_release_index, settings, release)
    paths: set[str] = set()
    for chunk in payload.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        if chunk.get("document_id") != document_id or chunk.get("version_id") != version_id:
            continue
        for image in chunk.get("images") or []:
            if isinstance(image, dict) and isinstance(image.get("path"), str):
                paths.add(image["path"].removeprefix("assets/"))
    return paths


def _read_release_index(
    settings: PortalSettings,
    release: ReleaseRecord,
) -> dict[str, Any]:
    local_path = settings.release_artifact_dir / release.release_id / INDEX_RELATIVE_PATH
    if local_path.is_file():
        payload = local_path.read_bytes()
    elif release.artifact_bucket and release.artifact_object_prefix:
        bucket = _storage_bucket(release.artifact_bucket)
        blob = bucket.blob(
            f"{release.artifact_object_prefix.rstrip('/')}/{INDEX_RELATIVE_PATH}",
            generation=release.index_generation,
        )
        payload = blob.download_as_bytes()
    else:
        raise FileNotFoundError("Published release index is unavailable.")
    if release.index_sha256 and hashlib.sha256(payload).hexdigest() != release.index_sha256:
        raise ValueError("Published release index failed integrity verification.")
    parsed = json.loads(payload.decode("utf-8"))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("chunks"), list):
        raise TypeError("Published release index is invalid.")
    return parsed


def _read_published_asset(
    settings: PortalSettings,
    release: ReleaseRecord,
    asset_slug: str,
    filename: str,
) -> tuple[bytes, str]:
    relative_path = f"assets/{asset_slug}/{filename}"
    local_path = settings.release_artifact_dir / release.release_id / relative_path
    if local_path.is_file():
        return local_path.read_bytes(), asset_content_type(local_path.suffix)
    if not release.artifact_bucket or not release.artifact_object_prefix:
        raise FileNotFoundError(filename)
    bucket = _storage_bucket(release.artifact_bucket)
    blob = bucket.blob(f"{release.artifact_object_prefix.rstrip('/')}/{relative_path}")
    try:
        payload = blob.download_as_bytes()
    except Exception as error:  # noqa: BLE001 - external storage boundary
        raise FileNotFoundError(filename) from error
    return payload, asset_content_type(Path(filename).suffix)


def _storage_bucket(bucket_name: str) -> Any:
    try:
        from google.cloud import storage
    except ImportError as error:  # pragma: no cover - optional deployment dependency
        raise RuntimeError("google-cloud-storage is required for knowledge assets.") from error
    return storage.Client().bucket(bucket_name)
