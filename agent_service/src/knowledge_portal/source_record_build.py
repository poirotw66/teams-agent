"""Helpers for building SourceCatalogEntry rows from release chunks/manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_core.source_identity import make_source_ref_id, safe_source_path
from platform_kernel.ports.source_catalog import SourceCatalogEntry

from .models import ReleaseRecord


def resolve_chunk_identity(
    chunk: dict[str, Any],
    *,
    release: ReleaseRecord,
    manifest_by_doc: dict[str, Any],
    source_path: str,
) -> tuple[str, Any, str]:
    """Return (document_id, manifest_entry, version_id) for an index chunk."""
    document_id = str(
        chunk.get("document_id") or chunk.get("documentId") or ""
    ).strip()
    entry = manifest_by_doc.get(document_id) if document_id else None
    if entry is None and source_path:
        for candidate in release.manifest:
            if candidate.source_path == source_path:
                entry = candidate
                document_id = candidate.document_id
                break
    if not document_id:
        document_id = Path(source_path).stem if source_path else ""
        entry = manifest_by_doc.get(document_id) or entry
    version_id = str(
        chunk.get("version_id")
        or chunk.get("versionId")
        or (entry.version_id if entry else "")
        or ""
    ).strip()
    return document_id, entry, version_id


def acl_groups_for_chunk(chunk: dict[str, Any], entry: Any) -> list[str]:
    raw_acl = chunk.get("acl_groups")
    if raw_acl is None:
        raw_acl = chunk.get("allowed_groups")
    if raw_acl is not None:
        cleaned = [str(group).strip() for group in raw_acl if str(group).strip()]
        return cleaned if cleaned else ["grp_public"]
    if entry and getattr(entry, "acl_groups", None):
        return [
            str(group).strip() for group in entry.acl_groups if str(group).strip()
        ] or ["grp_restricted"]
    return ["grp_restricted"]


def catalog_entry_from_chunk(
    chunk: dict[str, Any],
    *,
    release: ReleaseRecord,
    tenant_id: str,
    manifest_by_doc: dict[str, Any],
    seen: set[str],
    doc_chunk_acls: dict[str, list[str]],
) -> SourceCatalogEntry | None:
    source_path = safe_source_path(str(chunk.get("source_path") or ""))
    document_id, entry, version_id = resolve_chunk_identity(
        chunk,
        release=release,
        manifest_by_doc=manifest_by_doc,
        source_path=source_path,
    )
    chunk_id = str(chunk.get("chunk_id") or chunk.get("chunkId") or "").strip() or None
    source_ref_id = make_source_ref_id(
        release_id=release.release_id,
        document_id=document_id or None,
        version_id=version_id or None,
        chunk_id=chunk_id,
        source_path=source_path,
    )
    if not source_ref_id or source_ref_id in seen:
        return None
    seen.add(source_ref_id)
    artifact_ref = entry.artifact_ref if entry else None
    mapping_status = (
        "AVAILABLE"
        if artifact_ref or (entry and entry.original_asset_available)
        else "ORIGINAL_NOT_PRESERVED"
    )
    chunk_acl = acl_groups_for_chunk(chunk, entry)
    if document_id:
        doc_chunk_acls.setdefault(document_id, []).extend(chunk_acl)
    return SourceCatalogEntry(
        source_ref_id=source_ref_id,
        tenant_id=tenant_id,
        document_id=document_id or "unknown",
        version_id=version_id or "unknown",
        release_id=release.release_id,
        chunk_id=chunk_id,
        artifact_ref=artifact_ref,
        content_hash=str(
            chunk.get("content_hash") or (entry.content_hash if entry else "") or ""
        ),
        mapping_status=mapping_status,
        source_type=str(
            (entry.source_type if entry else None)
            or chunk.get("source_type")
            or "DERIVED_MARKDOWN"
        ),
        title=str((entry.title if entry else None) or chunk.get("title") or document_id),
        source_path=source_path or (entry.source_path if entry else None),
        excerpt=str(chunk.get("text") or chunk.get("content") or "")[:500] or None,
        original_asset_name=entry.original_asset_name if entry else None,
        acl_groups=tuple(chunk_acl),
    )


def catalog_entry_from_manifest(
    entry: Any,
    *,
    release: ReleaseRecord,
    tenant_id: str,
    seen: set[str],
    doc_chunk_acls: dict[str, list[str]],
) -> SourceCatalogEntry | None:
    source_ref_id = make_source_ref_id(
        release_id=release.release_id,
        document_id=entry.document_id,
        version_id=entry.version_id,
        chunk_id=None,
        source_path=entry.source_path,
    )
    if not source_ref_id or source_ref_id in seen:
        return None
    seen.add(source_ref_id)
    mapping_status = (
        "AVAILABLE"
        if entry.artifact_ref or entry.original_asset_available
        else "ORIGINAL_NOT_PRESERVED"
    )
    if getattr(entry, "acl_groups", None):
        doc_acl = [
            str(group).strip() for group in entry.acl_groups if str(group).strip()
        ] or ["grp_restricted"]
    elif doc_chunk_acls.get(entry.document_id):
        unique_groups = list(dict.fromkeys(doc_chunk_acls[entry.document_id]))
        doc_acl = unique_groups if unique_groups else ["grp_restricted"]
    else:
        doc_acl = ["grp_restricted"]
    return SourceCatalogEntry(
        source_ref_id=source_ref_id,
        tenant_id=tenant_id,
        document_id=entry.document_id,
        version_id=entry.version_id,
        release_id=release.release_id,
        artifact_ref=entry.artifact_ref,
        content_hash=entry.content_hash,
        mapping_status=mapping_status,
        source_type=entry.source_type,
        title=entry.title,
        source_path=entry.source_path,
        original_asset_name=entry.original_asset_name,
        acl_groups=tuple(doc_acl),
    )
