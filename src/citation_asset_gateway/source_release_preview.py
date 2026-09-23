"""Resolve citation previews from the immutable GCS knowledge release."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from .settings_contract import CitationGatewaySettings

logger = logging.getLogger(__name__)

MAX_CHUNKS_INDEX_BYTES = 8 * 1024 * 1024
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_SOURCE_REF_RE = re.compile(r"^src-[0-9a-f]{24}$")


@dataclass(frozen=True)
class ReleaseCitationPreview:
    title: str
    release_id: str
    source_path: str
    excerpt: str


def citation_source_ref_id(
    *,
    release_id: str | None,
    document_id: str | None,
    version_id: str | None,
    chunk_id: str | None,
    source_path: str | None,
) -> str | None:
    """Match ``knowledge_core.source_identity.make_source_ref_id`` exactly."""

    if not chunk_id and not source_path:
        return None
    payload = "\x1f".join(
        str(value or "")
        for value in (release_id, document_id, version_id, chunk_id, source_path)
    )
    return f"src-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _safe_source_path(source_path: str | None) -> str | None:
    if not source_path:
        return None
    candidate = str(source_path).replace("\\", "/")
    if "://" in candidate or candidate.startswith(("/", "~")):
        return None
    if "?" in candidate or "#" in candidate:
        candidate = candidate.split("?", 1)[0].split("#", 1)[0]
    parts = [part for part in candidate.split("/") if part not in {"", "."}]
    if ".." in parts:
        return None
    return "/".join(parts) or None


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _chunk_matches_source_ref(chunk: dict[str, Any], *, release_id: str, source_ref_id: str) -> bool:
    source_path = _safe_source_path(
        _text(chunk.get("source_path") or chunk.get("sourcePath"))
    )
    document_id = _text(chunk.get("document_id") or chunk.get("documentId"))
    version_id = _text(chunk.get("version_id") or chunk.get("versionId"))
    chunk_id = _text(chunk.get("chunk_id") or chunk.get("chunkId"))
    candidates = {
        release_id,
        _text(chunk.get("release_id") or chunk.get("releaseId")),
    }
    return any(
        citation_source_ref_id(
            release_id=candidate,
            document_id=document_id,
            version_id=version_id,
            chunk_id=chunk_id,
            source_path=source_path,
        )
        == source_ref_id
        for candidate in candidates
        if candidate
    )


def resolve_release_citation_preview(
    settings: CitationGatewaySettings,
    *,
    source_ref_id: str,
    tenant_id: str,
) -> ReleaseCitationPreview | None:
    """Find one cited document in the GCS release tree after Source API misses."""

    source_ref = str(source_ref_id or "").strip()
    if not _SOURCE_REF_RE.fullmatch(source_ref):
        return None
    if not settings.asset_gcs_bucket or not _SAFE_IDENTIFIER.fullmatch(tenant_id):
        return None
    for release_id in _preferred_release_ids(settings, tenant_id):
        preview = _preview_in_release(
            settings,
            release_id=release_id,
            tenant_id=tenant_id,
            source_ref_id=source_ref,
        )
        if preview is not None:
            return preview
    return None


def _preview_in_release(
    settings: CitationGatewaySettings,
    *,
    release_id: str,
    tenant_id: str,
    source_ref_id: str,
) -> ReleaseCitationPreview | None:
    chunks = _load_release_chunks(settings, tenant_id=tenant_id, release_id=release_id)
    for chunk in chunks:
        if not _chunk_matches_source_ref(chunk, release_id=release_id, source_ref_id=source_ref_id):
            continue
        source_path = _safe_source_path(
            _text(chunk.get("source_path") or chunk.get("sourcePath"))
        )
        if not source_path:
            continue
        title = _text(chunk.get("title")) or source_path
        excerpt = str(chunk.get("content") or "").strip()
        return ReleaseCitationPreview(
            title=title,
            release_id=release_id,
            source_path=source_path,
            excerpt=excerpt,
        )
    return None


def release_preview_payload(preview: ReleaseCitationPreview) -> dict[str, object]:
    return {
        "title": preview.title,
        "releaseId": preview.release_id,
        "sourcePath": preview.source_path,
        "mappingStatus": "AVAILABLE",
        "message": "此來源依知識庫版本呈現。",
        "evidence": {"excerpt": preview.excerpt[:2000]},
        "actions": {"canDownloadOriginal": False},
    }


def _preferred_release_ids(settings: CitationGatewaySettings, tenant_id: str) -> list[str]:
    listed = _list_release_ids(settings, tenant_id)
    preferred = _active_release_id_from_firestore()
    if preferred and preferred in listed:
        return [preferred, *[item for item in listed if item != preferred]]
    return listed


def _active_release_id_from_firestore() -> str | None:
    try:
        from google.cloud import firestore
    except ImportError:
        return None
    try:
        snapshot = firestore.Client().collection("knowledge_portal_config").document(
            "active_release"
        ).get()
    except Exception:
        logger.debug("Unable to read Firestore active_release pointer", exc_info=True)
        return None
    if not snapshot.exists:
        return None
    payload = snapshot.to_dict() or {}
    value = payload.get("release_id") or payload.get("releaseId")
    text = str(value or "").strip()
    return text if text and _SAFE_IDENTIFIER.fullmatch(text) else None


def _list_release_ids(settings: CitationGatewaySettings, tenant_id: str) -> list[str]:
    prefix = (
        f"{settings.asset_gcs_prefix.strip('/')}/tenants/{tenant_id}/releases/"
    ).lstrip("/")
    try:
        from google.cloud import storage
    except ImportError:
        return []
    client = storage.Client()
    iterator = client.list_blobs(settings.asset_gcs_bucket, prefix=prefix, delimiter="/")
    list(iterator)
    release_ids: list[str] = []
    for raw in getattr(iterator, "prefixes", ()) or ():
        name = str(raw).rstrip("/").rsplit("/", 1)[-1]
        if _SAFE_IDENTIFIER.fullmatch(name):
            release_ids.append(name)
    return sorted(release_ids, reverse=True)


def _load_release_chunks(
    settings: CitationGatewaySettings,
    *,
    tenant_id: str,
    release_id: str,
) -> list[dict[str, Any]]:
    object_name = (
        f"{settings.asset_gcs_prefix.strip('/')}/tenants/{tenant_id}"
        f"/releases/{release_id}/index/chunks.json"
    ).lstrip("/")
    try:
        from google.cloud import storage
    except ImportError:
        return []
    blob = storage.Client().bucket(settings.asset_gcs_bucket).blob(object_name)
    try:
        blob.reload()
        if blob.size is not None and blob.size > MAX_CHUNKS_INDEX_BYTES:
            logger.warning("release_chunks_index_too_large release_id=%s", release_id)
            return []
        raw = blob.download_as_bytes()
    except Exception:
        logger.debug("Unable to load release chunks for %s", release_id, exc_info=True)
        return []
    if len(raw) > MAX_CHUNKS_INDEX_BYTES:
        return []
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    chunks = payload.get("chunks") if isinstance(payload, dict) else payload
    if not isinstance(chunks, list):
        return []
    return [chunk for chunk in chunks if isinstance(chunk, dict)]


__all__ = [
    "ReleaseCitationPreview",
    "citation_source_ref_id",
    "release_preview_payload",
    "resolve_release_citation_preview",
]
