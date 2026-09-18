"""Release-scoped source resolution helpers shared by Agent and Backoffice.

Pure path/manifest helpers for resolving citation identity without Agent runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_core.source_identity import source_path_stem

__all__ = [
    "ResolvedSource",
    "find_manifest_entry",
    "manifest_by_key",
    "original_asset_path",
]


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


def manifest_by_key(
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


def find_manifest_entry(
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


def original_asset_path(
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


# Compatibility aliases for historical private call sites.
_manifest_by_key = manifest_by_key
_find_manifest_entry = find_manifest_entry
_original_asset_path = original_asset_path
