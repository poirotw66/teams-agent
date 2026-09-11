"""Stable source-reference helpers shared by retrieval and backoffice reads.

The retrieval index deliberately stores derived Markdown because it is the
search artifact.  A citation must still identify the exact document version
and release that produced the hit.  This module keeps that identity opaque in
URLs while allowing a trusted backend to resolve it back to a release artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .documents import DocumentChunk

_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def make_source_ref_id(
    *,
    release_id: str | None,
    document_id: str | None,
    version_id: str | None,
    chunk_id: str | None,
    source_path: str | None = None,
) -> str | None:
    """Return a stable, opaque identifier for one cited index chunk."""

    if not chunk_id and not source_path:
        return None
    payload = "\x1f".join(
        str(value or "")
        for value in (release_id, document_id, version_id, chunk_id, source_path)
    )
    return f"src-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def source_path_stem(source_path: str | None) -> str | None:
    if not source_path:
        return None
    return Path(source_path.replace("\\", "/")).stem or None


def safe_source_path(source_path: str | None) -> str | None:
    """Only expose repository-relative source paths, never signed/blob URLs."""

    if not source_path:
        return None
    candidate = str(source_path).replace("\\", "/")
    if "://" in candidate or candidate.startswith(("/", "~")):
        return "[REDACTED_SOURCE]"
    if "?" in candidate or "#" in candidate:
        candidate = candidate.split("?", 1)[0].split("#", 1)[0]
    parts = [part for part in candidate.split("/") if part not in {"", "."}]
    if ".." in parts:
        return "[REDACTED_SOURCE]"
    return "/".join(parts) or None


def _manifest_by_key(release_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
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
            chunk.document_id = chunk.document_id or str(
                entry.get("document_id") or entry.get("documentId") or ""
            ) or None
            chunk.version_id = chunk.version_id or str(
                entry.get("version_id") or entry.get("versionId") or ""
            ) or None
            chunk.source_type = chunk.source_type or str(
                entry.get("source_type") or entry.get("sourceType") or ""
            ) or None
        chunk.release_id = chunk.release_id or release_id
        original = _original_asset_path(
            release_root,
            document_id=chunk.document_id,
            version_id=chunk.version_id,
        )
        if original:
            chunk.original_asset_available = True
            chunk.original_asset_name = original.name


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
