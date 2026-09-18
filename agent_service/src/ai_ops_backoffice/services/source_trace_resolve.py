"""Citation and source-ref resolution helpers for source trace."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from knowledge_core.source_identity import make_source_ref_id, safe_source_path, source_path_stem
from knowledge_core.source_resolution import (
    ResolvedSource,
    _find_manifest_entry,
    _original_asset_path,
)

from .source_models import MappingStatus
from .source_repository import BoundedSourceCache, SourceRecordRepository
from .source_trace_locator import build_locator, match_chunk
from .source_trace_mapping import resolved_to_source_record, source_record_to_resolved
from .source_trace_release import ReleaseLoad, list_release_ids, load_release

__all__ = [
    "resolve_citation",
    "resolve_source_ref",
]


def resolve_citation(
    *,
    releases_dir: Path,
    release_cache: dict[str, tuple[int, int, ReleaseLoad]],
    citation: dict[str, Any],
    fallback_release_id: str | None = None,
    tenant_id: str = "default",
) -> ResolvedSource | None:
    if not isinstance(citation, dict):
        return None
    explicit_ref = str(citation.get("sourceRefId") or "") or None
    target_release = str(citation.get("releaseId") or fallback_release_id or "") or None

    # F03: If releaseId is specified, search ONLY that release. Do not fallback!
    candidate_releases = [target_release] if target_release else list_release_ids(releases_dir)

    for release_id in candidate_releases:
        if not release_id:
            continue
        loaded = load_release(releases_dir, release_id, release_cache)
        if loaded is None:
            continue
        resolved = _resolve_in_release(
            release_id=release_id,
            loaded=loaded,
            citation=citation,
            explicit_ref=explicit_ref,
            tenant_id=tenant_id,
        )
        if resolved is not None:
            return resolved
    return None


def _resolve_in_release(
    *,
    release_id: str,
    loaded: ReleaseLoad,
    citation: dict[str, Any],
    explicit_ref: str | None,
    tenant_id: str,
) -> ResolvedSource | None:
    release_root, chunks, by_id, by_title = loaded
    chunk = match_chunk(chunks, citation)
    if chunk is None:
        return None

    chunk_source_path = safe_source_path(
        str(chunk.get("source_path") or chunk.get("sourcePath") or "")
    )
    chunk_title = str(chunk.get("title") or citation.get("title") or "") or None
    entry = _find_manifest_entry(
        source_path=chunk_source_path,
        title=chunk_title,
        document_id=(str(citation.get("documentId")) if citation.get("documentId") else None),
        by_id=by_id,
        by_title=by_title,
    )
    document_id = (
        str(
            citation.get("documentId")
            or chunk.get("document_id")
            or (entry or {}).get("document_id")
            or (entry or {}).get("documentId")
            or (source_path_stem(chunk_source_path) or "")
        )
        or None
    )
    actual_chunk_version = (
        str(
            chunk.get("version_id")
            or (entry or {}).get("version_id")
            or (entry or {}).get("versionId")
            or ""
        )
        or None
    )

    # F03: If version was specified in citation, enforce exact match with the actual chunk version
    expected_ver = citation.get("versionId")
    if expected_ver and actual_chunk_version and str(expected_ver) != str(actual_chunk_version):
        return None

    version_id = actual_chunk_version or (
        str(citation.get("versionId")) if citation.get("versionId") else None
    )
    resolved_release = str(citation.get("releaseId") or release_id)
    chunk_id = (
        str(citation.get("chunkId") or chunk.get("chunk_id") or chunk.get("chunkId") or "") or None
    )
    source_ref_id = explicit_ref or make_source_ref_id(
        release_id=resolved_release,
        document_id=document_id,
        version_id=version_id,
        chunk_id=chunk_id,
        source_path=chunk_source_path,
    )
    if not source_ref_id:
        return None

    return _build_resolved_source(
        release_root=release_root,
        citation=citation,
        chunk=chunk,
        entry=entry or {},
        chunk_source_path=chunk_source_path,
        chunk_title=chunk_title,
        document_id=document_id,
        version_id=version_id,
        resolved_release=resolved_release,
        chunk_id=chunk_id,
        source_ref_id=source_ref_id,
        tenant_id=tenant_id,
    )


def _build_resolved_source(
    *,
    release_root: Path,
    citation: dict[str, Any],
    chunk: dict[str, Any],
    entry: dict[str, Any],
    chunk_source_path: str,
    chunk_title: str | None,
    document_id: str | None,
    version_id: str | None,
    resolved_release: str,
    chunk_id: str | None,
    source_ref_id: str,
    tenant_id: str,
) -> ResolvedSource:
    original_path = _original_asset_path(
        release_root,
        document_id=document_id,
        version_id=version_id,
    )
    original_available = original_path is not None
    source_type = _resolve_source_type(citation, chunk, entry, original_path)
    had_complete_identity = all(
        citation.get(key)
        for key in ("sourceRefId", "documentId", "versionId", "releaseId", "sourcePath")
    )
    is_edited = bool(
        chunk.get("is_edited_derivative")
        or entry.get("is_edited_derivative")
        or citation.get("isEditedDerivative")
    )
    mapping_status = _mapping_status(
        is_edited=is_edited,
        had_complete_identity=had_complete_identity,
        original_available=original_available,
    )
    locator = build_locator(source_type, chunk, entry, citation)
    # Prefer authoritative tenant from release/manifest over request tenant (F02).
    authoritative_tenant = (
        str(entry.get("tenant_id") or chunk.get("tenant_id") or "").strip() or None
    )
    resolved_tenant = authoritative_tenant or tenant_id
    return ResolvedSource(
        source_ref_id=source_ref_id,
        title=chunk_title,
        document_id=document_id,
        version_id=version_id,
        release_id=resolved_release,
        chunk_id=chunk_id,
        source_path=chunk_source_path,
        content=str(chunk.get("content") or "") or None,
        source_type=source_type,
        original_asset_available=(original_available and had_complete_identity and not is_edited),
        original_asset_name=original_path.name if original_path else None,
        original_asset_path=original_path,
        trace_status="EXACT" if had_complete_identity else "LEGACY_UNVERIFIED",
        tenant_id=resolved_tenant,
        artifact_ref=str(entry.get("artifact_ref") or "") or None,
        mapping_status=mapping_status,
        locator=locator,
        owner_unit_id=str(entry.get("owner_unit_id") or "") or None,
        acl_groups=tuple(entry.get("acl_groups") or ()),
    )


def _resolve_source_type(
    citation: dict[str, Any],
    chunk: dict[str, Any],
    entry: dict[str, Any],
    original_path: Path | None,
) -> str:
    requested_type = str(citation.get("sourceType") or "").upper()
    manifest_type = str(
        entry.get("source_type") or entry.get("sourceType") or chunk.get("source_type") or ""
    ).upper()
    if requested_type or manifest_type:
        return requested_type or manifest_type
    if original_path and original_path.suffix.lower() == ".pdf":
        return "PDF"
    return "DERIVED_MARKDOWN"


def _mapping_status(
    *,
    is_edited: bool,
    had_complete_identity: bool,
    original_available: bool,
) -> str:
    if is_edited:
        return MappingStatus.EDITED_DERIVATIVE.value
    if not had_complete_identity:
        # Incomplete identity must not be labeled EXACT/AVAILABLE (F03).
        return MappingStatus.LEGACY_UNVERIFIED.value
    if original_available:
        return MappingStatus.AVAILABLE.value
    return MappingStatus.ORIGINAL_NOT_PRESERVED.value


def resolve_source_ref(
    *,
    releases_dir: Path,
    release_cache: dict[str, tuple[int, int, ReleaseLoad]],
    source_repository: SourceRecordRepository,
    cache: BoundedSourceCache,
    source_ref_id: str,
    tenant_id: str = "default",
) -> ResolvedSource | None:
    """Resolve a source reference directly using O(1) bounded cache and repository."""
    if not source_ref_id or not re.fullmatch(r"src-[0-9a-f]{24}", source_ref_id):
        return None

    # 1. Bounded LRU/TTL Cache Check (A06)
    cached = cache.get(tenant_id, source_ref_id)
    if cached is not None:
        return source_record_to_resolved(cached)

    # 2. Direct Repository Check (A06)
    rec = None
    if hasattr(source_repository, "get_source_record_sync"):
        rec = source_repository.get_source_record_sync(tenant_id, source_ref_id)
    if rec is not None:
        cache.put(rec)
        return source_record_to_resolved(rec)

    # 3. Fallback only for legacy unindexed release directories
    return _resolve_source_ref_from_releases(
        releases_dir=releases_dir,
        release_cache=release_cache,
        source_repository=source_repository,
        cache=cache,
        source_ref_id=source_ref_id,
        tenant_id=tenant_id,
    )


def _resolve_source_ref_from_releases(
    *,
    releases_dir: Path,
    release_cache: dict[str, tuple[int, int, ReleaseLoad]],
    source_repository: SourceRecordRepository,
    cache: BoundedSourceCache,
    source_ref_id: str,
    tenant_id: str,
) -> ResolvedSource | None:
    for release_id in list_release_ids(releases_dir):
        loaded = load_release(releases_dir, release_id, release_cache)
        if loaded is None:
            continue
        resolved = _match_source_ref_in_release(
            releases_dir=releases_dir,
            release_cache=release_cache,
            release_id=release_id,
            loaded=loaded,
            source_ref_id=source_ref_id,
            tenant_id=tenant_id,
        )
        if resolved is None:
            continue
        # Never let request tenant overwrite authoritative source tenant (F02).
        if (
            resolved.tenant_id
            and tenant_id
            and resolved.tenant_id != tenant_id
            and tenant_id not in {"default", "local-development"}
        ):
            continue
        record = resolved_to_source_record(resolved, tenant_id=resolved.tenant_id or tenant_id)
        if hasattr(source_repository, "save_source_record_sync"):
            source_repository.save_source_record_sync(record)
        cache.put(record)
        return resolved
    return None


def _match_source_ref_in_release(
    *,
    releases_dir: Path,
    release_cache: dict[str, tuple[int, int, ReleaseLoad]],
    release_id: str,
    loaded: ReleaseLoad,
    source_ref_id: str,
    tenant_id: str,
) -> ResolvedSource | None:
    _release_root, chunks, by_id, by_title = loaded
    for chunk in chunks:
        source_path = safe_source_path(str(chunk.get("source_path") or ""))
        entry = _find_manifest_entry(
            source_path=source_path,
            title=str(chunk.get("title") or ""),
            document_id=None,
            by_id=by_id,
            by_title=by_title,
        )
        document_id = (
            str(
                chunk.get("document_id")
                or (entry or {}).get("document_id")
                or (entry or {}).get("documentId")
                or (source_path_stem(source_path) or "")
            )
            or None
        )
        version_id = (
            str(
                chunk.get("version_id")
                or (entry or {}).get("version_id")
                or (entry or {}).get("versionId")
                or ""
            )
            or None
        )
        chunk_id = str(chunk.get("chunk_id") or chunk.get("chunkId") or "") or None
        expected = make_source_ref_id(
            release_id=release_id,
            document_id=document_id,
            version_id=version_id,
            chunk_id=chunk_id,
            source_path=source_path,
        )
        if expected != source_ref_id:
            continue
        return resolve_citation(
            releases_dir=releases_dir,
            release_cache=release_cache,
            citation={
                "sourceRefId": source_ref_id,
                "title": chunk.get("title"),
                "chunkId": chunk_id,
                "documentId": document_id,
                "versionId": version_id,
                "releaseId": release_id,
                "sourcePath": source_path,
            },
            fallback_release_id=release_id,
            tenant_id=tenant_id,
        )
    return None
