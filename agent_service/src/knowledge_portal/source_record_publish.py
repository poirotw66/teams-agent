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

from platform_kernel.ports.source_catalog import SourceCatalogEntry, SourceCatalogWriter

from .models import ReleaseRecord
from .settings import PortalSettings
from .source_record_build import catalog_entry_from_chunk, catalog_entry_from_manifest

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
        entry = catalog_entry_from_chunk(
            chunk,
            release=release,
            tenant_id=tenant_id,
            manifest_by_doc=manifest_by_doc,
            seen=seen,
            doc_chunk_acls=doc_chunk_acls,
        )
        if entry is not None:
            records.append(entry)

    for manifest_entry in release.manifest:
        entry = catalog_entry_from_manifest(
            manifest_entry,
            release=release,
            tenant_id=tenant_id,
            seen=seen,
            doc_chunk_acls=doc_chunk_acls,
        )
        if entry is not None:
            records.append(entry)
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
