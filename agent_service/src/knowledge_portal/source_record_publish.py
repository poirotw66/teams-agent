"""Persist source catalog entries when a knowledge release becomes active.

Backoffice originally created SourceRecords lazily on resolve. Portal publish
must write durable identity + artifact_ref so Cloud Run Adapter/Console can
open the exact version original without scanning container-local releases.

Persistence goes through ``SourceCatalogWriter`` so Portal does not import
Backoffice repository implementations.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agent_service.source_refs import make_source_ref_id, safe_source_path
from platform_kernel.ports.source_catalog import SourceCatalogEntry, SourceCatalogWriter

from .models import ReleaseRecord
from .settings import PortalSettings

logger = logging.getLogger(__name__)


def _load_chunks(index_artifact_uri: str | None) -> list[dict[str, Any]]:
    if not index_artifact_uri:
        return []
    path = Path(index_artifact_uri)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    chunks = payload.get("chunks") if isinstance(payload, dict) else None
    if isinstance(chunks, list):
        return [item for item in chunks if isinstance(item, dict)]
    return []


def build_source_records_for_release(
    release: ReleaseRecord,
    *,
    tenant_id: str,
) -> list[SourceCatalogEntry]:
    """Build neutral catalog entries for every indexed chunk in the release."""

    manifest_by_doc = {entry.document_id: entry for entry in release.manifest}
    records: list[SourceCatalogEntry] = []
    seen: set[str] = set()
    doc_chunk_acls: dict[str, list[str]] = {}

    for chunk in _load_chunks(release.index_artifact_uri):
        source_path = safe_source_path(str(chunk.get("source_path") or ""))
        document_id = str(
            chunk.get("document_id")
            or chunk.get("documentId")
            or ""
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
        chunk_id = str(chunk.get("chunk_id") or chunk.get("chunkId") or "").strip() or None
        source_ref_id = make_source_ref_id(
            release_id=release.release_id,
            document_id=document_id or None,
            version_id=version_id or None,
            chunk_id=chunk_id,
            source_path=source_path,
        )
        if not source_ref_id or source_ref_id in seen:
            continue
        seen.add(source_ref_id)
        artifact_ref = entry.artifact_ref if entry else None
        original_name = entry.original_asset_name if entry else None
        if artifact_ref or (entry and entry.original_asset_available):
            mapping_status = "AVAILABLE"
        else:
            mapping_status = "ORIGINAL_NOT_PRESERVED"

        raw_acl = chunk.get("acl_groups")
        if raw_acl is None:
            raw_acl = chunk.get("allowed_groups")
        if raw_acl is not None:
            cleaned = [str(group).strip() for group in raw_acl if str(group).strip()]
            chunk_acl = cleaned if cleaned else ["grp_public"]
        elif entry and getattr(entry, "acl_groups", None):
            chunk_acl = [
                str(group).strip() for group in entry.acl_groups if str(group).strip()
            ] or ["grp_restricted"]
        else:
            chunk_acl = ["grp_restricted"]

        if document_id:
            doc_chunk_acls.setdefault(document_id, []).extend(chunk_acl)

        records.append(
            SourceCatalogEntry(
                source_ref_id=source_ref_id,
                tenant_id=tenant_id,
                document_id=document_id or "unknown",
                version_id=version_id or "unknown",
                release_id=release.release_id,
                chunk_id=chunk_id,
                artifact_ref=artifact_ref,
                content_hash=str(
                    chunk.get("content_hash")
                    or (entry.content_hash if entry else "")
                    or ""
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
                original_asset_name=original_name,
                acl_groups=tuple(chunk_acl),
            )
        )

    for entry in release.manifest:
        source_ref_id = make_source_ref_id(
            release_id=release.release_id,
            document_id=entry.document_id,
            version_id=entry.version_id,
            chunk_id=None,
            source_path=entry.source_path,
        )
        if not source_ref_id or source_ref_id in seen:
            continue
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

        records.append(
            SourceCatalogEntry(
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
        )
    return records


async def persist_release_source_records(
    settings: PortalSettings,
    release: ReleaseRecord,
    *,
    writer: SourceCatalogWriter | None = None,
) -> int:
    """Write catalog entries for an activated release. Returns saved count.

    The writer must be supplied by the composition root. When absent, persistence
    is skipped (source_store_mode NONE / local tests without wiring).
    """

    if writer is None:
        return 0

    tenant_id = getattr(settings, "default_tenant_id", None) or "default"
    records = build_source_records_for_release(release, tenant_id=tenant_id)
    if not records:
        logger.info("No SourceRecords to persist for release %s", release.release_id)
        return 0

    saved = await writer.save_entries(records)
    logger.info(
        "Persisted %s SourceRecords for release %s",
        saved,
        release.release_id,
    )
    return saved
