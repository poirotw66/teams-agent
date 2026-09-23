"""Read-only inventory of documents in a local GCS knowledge mirror."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .knowledge_release_cache import require_safe_identifier, resolve_mirrored_release_dir
from .settings import RagSettings

logger = logging.getLogger(__name__)

_PREVIEW_CHARS = 240

__all__ = [
    "MirrorDocumentNotFound",
    "attach_mirror_documents",
    "cache_root_for_settings",
    "list_mirrored_release_documents",
    "preview_mirrored_document",
]


class MirrorDocumentNotFound(LookupError):
    """The requested document is not in the loaded GCS mirror."""


def cache_root_for_settings(settings: RagSettings) -> Path:
    return settings.knowledge_release_cache_dir or (
        settings.data_dir / "knowledge_cache"
    )


def list_mirrored_release_documents(
    *,
    cache_root: Path,
    tenant_id: str,
    release_id: str | None,
) -> list[dict[str, str | None]]:
    """Return manifest documents for a verified-or-present local GCS mirror.

    Absence of a mirror is valid and returns an empty list. A corrupt manifest
    is logged and also returns an empty list so status APIs stay available.
    """
    if not release_id:
        return []
    try:
        release_dir = resolve_mirrored_release_dir(
            cache_root,
            tenant_id=tenant_id,
            release_id=release_id,
        )
    except ValueError:
        return []
    if release_dir is None:
        return []
    manifest = _read_json_object(release_dir / "manifest.json")
    if manifest is None:
        return []
    catalog_titles = _catalog_titles(release_dir / "catalog" / "service_catalog.json")
    documents: list[dict[str, str | None]] = []
    for entry in manifest.get("documents") or []:
        if not isinstance(entry, dict):
            continue
        document_id = _optional_text(entry.get("document_id"))
        if not document_id:
            continue
        title = _optional_text(entry.get("title")) or catalog_titles.get(document_id)
        documents.append(
            {
                "documentId": document_id,
                "title": title,
                "versionId": _optional_text(entry.get("version_id")),
                "sourcePath": _optional_text(entry.get("source_path")),
                "contentState": _optional_text(entry.get("content_state")),
            }
        )
    return documents


def preview_mirrored_document(
    *,
    settings: RagSettings,
    release_id: str | None,
    document_id: str,
) -> dict[str, object]:
    """Return published GCS-mirror chunks for one document. Vectors are omitted."""
    safe_document_id = require_safe_identifier("document", document_id)
    if not release_id:
        raise MirrorDocumentNotFound("No knowledge release is loaded.")
    cache_root = cache_root_for_settings(settings)
    documents = list_mirrored_release_documents(
        cache_root=cache_root,
        tenant_id=settings.knowledge_release_tenant_id,
        release_id=release_id,
    )
    meta = next(
        (item for item in documents if item.get("documentId") == safe_document_id),
        None,
    )
    if meta is None:
        raise MirrorDocumentNotFound(
            f"Document '{safe_document_id}' is not in the loaded GCS mirror."
        )
    release_dir = resolve_mirrored_release_dir(
        cache_root,
        tenant_id=settings.knowledge_release_tenant_id,
        release_id=release_id,
    )
    if release_dir is None:
        raise MirrorDocumentNotFound("Local GCS mirror directory is missing.")
    index = _read_json_object(release_dir / "index" / "chunks.json")
    if index is None:
        raise FileNotFoundError(
            "QA snapshot is missing index/chunks.json; cannot preview mirror chunks."
        )
    source_path = meta.get("sourcePath")
    chunks = [
        _to_preview_chunk(raw)
        for raw in index.get("chunks") or []
        if isinstance(raw, dict)
        and _chunk_belongs_to_document(raw, safe_document_id, source_path)
    ]
    return {
        "releaseId": release_id,
        "documentId": safe_document_id,
        "title": meta.get("title"),
        "versionId": meta.get("versionId"),
        "sourcePath": source_path,
        "contentState": meta.get("contentState"),
        "chunkCount": len(chunks),
        "chunks": chunks,
    }


def attach_mirror_documents(
    payload: dict[str, object],
    *,
    settings: RagSettings,
    release_id: str | None,
) -> dict[str, object]:
    """Copy *payload* and attach ``documents`` from the local GCS mirror."""
    documents = list_mirrored_release_documents(
        cache_root=cache_root_for_settings(settings),
        tenant_id=settings.knowledge_release_tenant_id,
        release_id=release_id,
    )
    return {**payload, "documents": documents}


def _catalog_titles(catalog_path: Path) -> dict[str, str]:
    payload = _read_json_object(catalog_path)
    if payload is None:
        return {}
    titles: dict[str, str] = {}
    for service in payload.get("services") or []:
        if not isinstance(service, dict):
            continue
        document_id = _optional_text(service.get("documentId"))
        official_name = _optional_text(service.get("officialName"))
        if document_id and official_name:
            titles[document_id] = official_name
    return titles


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("Unable to read knowledge mirror JSON %s: %s", path, error)
        return None
    return payload if isinstance(payload, dict) else None


def _chunk_belongs_to_document(
    raw: dict[str, Any],
    document_id: str,
    source_path: str | None,
) -> bool:
    raw_document_id = _optional_text(raw.get("document_id"))
    if raw_document_id:
        return raw_document_id == document_id
    return bool(source_path) and _optional_text(raw.get("source_path")) == source_path


def _to_preview_chunk(raw: dict[str, Any]) -> dict[str, object]:
    content = raw.get("content")
    text = content.strip() if isinstance(content, str) else ""
    chunk_id = _optional_text(raw.get("chunk_id")) or _optional_text(raw.get("id"))
    title = _optional_text(raw.get("title")) or "未命名段落"
    token_count = raw.get("token_count")
    return {
        "id": chunk_id or "chunk",
        "parent_id": _optional_text(raw.get("parent_id")),
        "neighbor_ids": _string_list(raw.get("neighbor_ids")),
        "title": title,
        "content": text or None,
        "content_preview": text[:_PREVIEW_CHARS],
        "character_count": len(text),
        "token_count": token_count if isinstance(token_count, int) else None,
        "page_number": _optional_int(
            raw.get("page") if raw.get("page") is not None else raw.get("page_index")
        ),
        "page_end": _optional_int(raw.get("page_end")),
        "heading_path": _string_list(raw.get("heading_path") or raw.get("section_path")),
        "content_hash": _optional_text(raw.get("content_hash")),
        "parser_version": _optional_text(raw.get("parser_version")),
        "chunker_version": _optional_text(raw.get("chunker_version")),
        "source_path": _optional_text(raw.get("source_path")),
        "quality_issues": [],
        "images": _preview_images(raw.get("images")),
    }


def _preview_images(value: object) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        return []
    images: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = _optional_text(item.get("path") or item.get("filename"))
        if not path:
            continue
        images.append(
            {
                "path": path,
                "filename": _optional_text(item.get("filename")) or path.rsplit("/", 1)[-1],
                "alt_text": _optional_text(item.get("alt_text") or item.get("alt")),
                "content_type": _optional_text(item.get("content_type")),
                "url": _optional_text(item.get("url")),
            }
        )
    return images


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
