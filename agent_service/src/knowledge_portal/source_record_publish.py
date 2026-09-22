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


def _parse_gcs_uri(uri: str) -> tuple[str, str] | None:
    """Return ``(bucket, object_name)`` for ``gs://bucket/object`` URIs."""
    if not uri.startswith("gs://"):
        return None
    remainder = uri[5:]
    bucket, sep, object_name = remainder.partition("/")
    if not sep or not bucket or not object_name:
        return None
    return bucket, object_name


def _load_chunks_payload(raw: bytes | str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    chunks = payload.get("chunks") if isinstance(payload, dict) else None
    if isinstance(chunks, list):
        return [item for item in chunks if isinstance(item, dict)]
    return []


def _load_chunks_from_gcs(index_artifact_uri: str) -> list[dict[str, Any]]:
    """Read ``index/chunks.json`` from GCS when Portal stored a ``gs://`` URI.

    Inventory republish and cloud finalize often set ``index_artifact_uri`` to a
    GCS object rather than a container-local path. Without this branch,
    ``build_source_records_for_release`` skips chunk-level identities, so Agent
    citations (hashed with chunk_id) cannot be resolved by Backoffice preview.
    """
    parsed = _parse_gcs_uri(index_artifact_uri)
    if parsed is None:
        return []
    bucket_name, object_name = parsed
    try:
        from google.cloud import storage
    except ImportError:
        logger.warning(
            "google-cloud-storage unavailable; cannot load SourceRecord chunks from %s",
            index_artifact_uri,
        )
        return []
    try:
        blob = storage.Client().bucket(bucket_name).blob(object_name)
        return _load_chunks_payload(blob.download_as_bytes())
    except Exception:  # noqa: BLE001 - boundary: GCS download failures
        logger.exception(
            "Failed loading SourceRecord chunks from GCS uri %s",
            index_artifact_uri,
        )
        return []


def _load_chunks(index_artifact_uri: str | None) -> list[dict[str, Any]]:
    if not index_artifact_uri:
        return []
    path = Path(index_artifact_uri)
    if path.is_file():
        try:
            return _load_chunks_payload(path.read_text(encoding="utf-8"))
        except OSError:
            return []
    if index_artifact_uri.startswith("gs://"):
        return _load_chunks_from_gcs(index_artifact_uri)
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
