"""Stable source-reference helpers shared by retrieval and backoffice reads.

The retrieval index deliberately stores derived Markdown because it is the
search artifact.  A citation must still identify the exact document version
and release that produced the hit.  This module keeps that identity opaque in
URLs while allowing a trusted backend to resolve it back to a release artifact.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from knowledge_core.source_identity import (
    make_source_ref_id,
    safe_source_path,
    source_path_stem,
)

from .documents import DocumentChunk, DocumentImage, extract_images

_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def build_citation_url(
    *,
    source_base_url: str | None,
    source_path: str | None,
    source_ref_id: str | None = None,
) -> str | None:
    """Compose a clickable citation URL when a formal base URL is configured.

    Prefer ``source_path`` under ``source_base_url``. When path is unavailable,
    fall back to a durable ``/citations/{sourceRefId}`` identity link. Returns
    ``None`` when no base URL is configured so callers can leave enrichment to
    the Teams adapter signed ``/rag-sources/`` path.
    """

    base = (source_base_url or "").strip().rstrip("/")
    if not base:
        return None
    safe_path = safe_source_path(source_path)
    if safe_path and safe_path != "[REDACTED_SOURCE]":
        return f"{base}/{quote(safe_path, safe='/')}"
    if source_ref_id and str(source_ref_id).strip():
        return f"{base}/citations/{quote(str(source_ref_id).strip(), safe='')}"
    return None


def _manifest_by_key(
    release_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}, {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    documents = payload.get("documents") or []
    by_id: dict[str, dict[str, Any]] = {}
    by_title: dict[str, list[dict[str, Any]]] = {}
    for item in documents:
        if not isinstance(item, dict):
            continue
        document_id = item.get("document_id") or item.get("documentId")
        title = item.get("title")
        if document_id:
            by_id[str(document_id)] = item
        if title:
            by_title.setdefault(str(title).casefold(), []).append(item)
    return by_id, by_title


def _find_manifest_entry(
    *,
    source_path: str | None,
    title: str | None,
    document_id: str | None,
    by_id: dict[str, dict[str, Any]],
    by_title: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if document_id and document_id in by_id:
        return by_id[document_id]
    stem = source_path_stem(source_path)
    if stem and stem in by_id:
        return by_id[stem]
    matches = by_title.get(str(title or "").casefold(), [])
    return matches[0] if len(matches) == 1 else None


def _original_asset_path(
    release_dir: Path,
    *,
    document_id: str | None,
    version_id: str | None,
) -> Path | None:
    """Find a future/private original asset without exposing its path."""

    if not document_id or not version_id:
        return None
    original_root = release_dir / "original"
    if not original_root.is_dir():
        return None
    candidate_root = (original_root / document_id / version_id).resolve()
    try:
        candidate_root.relative_to(original_root.resolve())
    except ValueError:
        return None
    if not candidate_root.is_dir():
        return None
    for candidate in sorted(candidate_root.iterdir()):
        if candidate.is_file():
            return candidate
    return None


def hydrate_index_sources(
    chunks: Iterable[DocumentChunk],
    *,
    release_dir: Path | None,
    release_id: str | None,
) -> None:
    """Attach release/manifest identity to chunks loaded from an index.

    Older index artifacts do not contain these fields.  Hydration is therefore
    best-effort and intentionally leaves the original chunk content untouched.
    """

    if release_dir is None or not release_id or not _SAFE_RELEASE_ID.fullmatch(release_id):
        for chunk in chunks:
            if release_id and not chunk.release_id:
                chunk.release_id = release_id
        return

    release_root = (release_dir / release_id).resolve()
    try:
        release_root.relative_to(release_dir.resolve())
    except ValueError:
        return
    by_id, by_title = _manifest_by_key(release_root)
    for chunk in chunks:
        entry = _find_manifest_entry(
            source_path=chunk.source_path,
            title=chunk.title,
            document_id=chunk.document_id,
            by_id=by_id,
            by_title=by_title,
        )
        if entry:
            chunk.document_id = (
                chunk.document_id
                or str(entry.get("document_id") or entry.get("documentId") or "")
                or None
            )
            chunk.version_id = (
                chunk.version_id
                or str(entry.get("version_id") or entry.get("versionId") or "")
                or None
            )
            if chunk.version_number is None:
                raw_version_number = entry.get("version_number") or entry.get("versionNumber")
                if raw_version_number is not None:
                    try:
                        chunk.version_number = int(raw_version_number)
                    except (TypeError, ValueError):
                        chunk.version_number = None
            chunk.source_type = (
                chunk.source_type
                or str(entry.get("source_type") or entry.get("sourceType") or "")
                or None
            )
            aliases = entry.get("source_aliases") or entry.get("sourceAliases") or []
            if not chunk.source_aliases and isinstance(aliases, list):
                chunk.source_aliases = [
                    str(alias).strip() for alias in aliases if str(alias).strip()
                ]
            chunk.content_state = str(
                entry.get("content_state") or entry.get("contentState") or chunk.content_state
            )
            chunk.effective_at = (
                chunk.effective_at
                or str(entry.get("effective_at") or entry.get("effectiveAt") or "")
                or None
            )
            chunk.expires_at = (
                chunk.expires_at
                or str(entry.get("expires_at") or entry.get("expiresAt") or "")
                or None
            )
            environments = (
                entry.get("applicable_environments") or entry.get("applicableEnvironments") or []
            )
            if not chunk.applicable_environments and isinstance(environments, list):
                chunk.applicable_environments = [
                    str(environment).strip()
                    for environment in environments
                    if str(environment).strip()
                ]
        chunk.release_id = release_id
        original = _original_asset_path(
            release_root,
            document_id=chunk.document_id,
            version_id=chunk.version_id,
        )
        if original:
            chunk.original_asset_available = True
            chunk.original_asset_name = original.name
    _attach_missing_release_images(
        chunks,
        release_root=release_root,
        corpus_assets=release_dir.parent / "sources" / "assets",
    )


def _attach_missing_release_images(
    chunks: Iterable[DocumentChunk],
    *,
    release_root: Path,
    corpus_assets: Path,
) -> None:
    """Fill images missing from an already published index.

    Publishing used to look for images next to the wrong directory, so older
    releases have empty image lists even when the Markdown still cites them.
    Loading reattaches those images without rewriting chunk text or embeddings.
    """

    grouped: dict[str, list[DocumentChunk]] = {}
    for chunk in chunks:
        if not chunk.source_path:
            continue
        grouped.setdefault(chunk.source_path, []).append(chunk)
    asset_roots = [release_root / "assets", corpus_assets]
    for source_path, source_chunks in grouped.items():
        if any(chunk.images for chunk in source_chunks):
            continue
        markdown_path = _safe_release_file(release_root, source_path)
        if markdown_path is None or not markdown_path.is_file():
            continue
        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        except OSError:
            continue
        images = extract_images(markdown, markdown_path, asset_roots=asset_roots)
        if images:
            _assign_images_to_chunks(source_chunks, images)


def _assign_images_to_chunks(
    chunks: list[DocumentChunk],
    images: list[DocumentImage],
) -> None:
    assigned: dict[str, list[DocumentImage]] = {}
    unmatched: list[DocumentImage] = []
    for image in images:
        target = _chunk_matching_image(chunks, image)
        if target is None:
            unmatched.append(image)
            continue
        assigned.setdefault(target.chunk_id, []).append(image)
    if unmatched:
        assigned.setdefault(chunks[0].chunk_id, []).extend(unmatched)
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    for chunk_id, chunk_images in assigned.items():
        by_id[chunk_id].images = chunk_images


def _chunk_matching_image(
    chunks: list[DocumentChunk],
    image: DocumentImage,
) -> DocumentChunk | None:
    label = image.alt_text.strip()
    if not label:
        return None
    return next((chunk for chunk in chunks if label in chunk.content), None)


def _safe_release_file(release_root: Path, source_path: str) -> Path | None:
    if not source_path or Path(source_path).is_absolute() or ".." in Path(source_path).parts:
        return None
    candidate = (release_root / source_path).resolve()
    try:
        candidate.relative_to(release_root.resolve())
    except ValueError:
        return None
    return candidate


@dataclass(frozen=True)
class ResolvedSource:
    """A source reference resolved from a release index."""

    source_ref_id: str
    title: str | None
    document_id: str | None
    version_id: str | None
    release_id: str | None
    chunk_id: str | None
    source_path: str | None
    content: str | None
    source_type: str
    original_asset_available: bool
    original_asset_name: str | None
    original_asset_path: Path | None
    trace_status: str
    tenant_id: str | None = None
    artifact_ref: str | None = None
    mapping_status: str = "AVAILABLE"
    locator: Any = None
    owner_unit_id: str | None = None
    acl_groups: tuple[str, ...] = ()
    is_archived: bool = False
    is_deleted: bool = False


__all__ = [
    "ResolvedSource",
    "hydrate_index_sources",
    "make_source_ref_id",
    "safe_source_path",
    "source_path_stem",
]
