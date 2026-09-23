"""Package enterprise service-catalog rows into a release artifact.

Governance progress (spec §2.3)
-------------------------------
* Pluggable draft store + state machine: see ``service_catalog_governance`` /
  ``service_catalog_draft_store`` (FILE local-dev; FIRESTORE multi-instance).
* Portal HTTP API: ``/api/catalog`` (draft save / submit / decide).
* Finalize prefers an APPROVED governed draft when present; otherwise derives
  rows from the document manifest (still one authoritative packaged file).

Still missing for full enterprise catalog governance:

* Live GCS publish/sync verification when bucket/tenant are configured.
* Dual-approval / SoD distinct from document publish RBAC.
* Backfill tooling that imports local-only aliases into cloud drafts without
  auto-overwriting cloud production rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_core.service_catalog import (
    SERVICE_CATALOG_SCHEMA_VERSION,
    validate_service_catalog_payload,
)
from knowledge_portal.models import ReleaseManifestEntry

SERVICE_CATALOG_RELATIVE_PATH = "catalog/service_catalog.json"
# Reserved for Portal catalog draft workflow; not written by publish finalize yet.
SERVICE_CATALOG_DRAFT_RELATIVE_PATH = "catalog/service_catalog.draft.json"

__all__ = [
    "SERVICE_CATALOG_DRAFT_RELATIVE_PATH",
    "SERVICE_CATALOG_RELATIVE_PATH",
    "SERVICE_CATALOG_SCHEMA_VERSION",
    "build_service_catalog_payload",
    "validate_service_catalog_payload",
    "write_service_catalog_artifact",
    "write_service_catalog_draft",
]


def build_service_catalog_payload(
    manifest: list[ReleaseManifestEntry],
    *,
    release_id: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Derive a publishable service-catalog snapshot from release documents.

    Full enterprise catalog governance (draft/review/publish of directory rows
    independent of documents) remains a later Portal workstream. This artifact
    freezes the document-linked service scope aliases that routing already uses
    so GCS mirrors can sync them via the ``catalog/`` inventory prefix.
    """
    services: list[dict[str, Any]] = []
    for entry in manifest:
        aliases = [
            str(alias).strip() for alias in (entry.source_aliases or []) if str(alias).strip()
        ]
        services.append(
            {
                "serviceId": entry.document_id,
                "officialName": entry.title,
                "aliases": aliases,
                "documentId": entry.document_id,
                "versionId": entry.version_id,
                "sourcePath": entry.source_path,
                "aclGroups": list(entry.acl_groups or []),
                "ownerUnitId": None,
            }
        )
    return validate_service_catalog_payload(
        {
            "schemaVersion": SERVICE_CATALOG_SCHEMA_VERSION,
            "releaseId": release_id,
            "tenantId": tenant_id,
            "services": services,
        }
    )


def write_service_catalog_artifact(
    release_dir: Path,
    *,
    release_id: str,
    tenant_id: str,
    manifest: list[ReleaseManifestEntry],
    governed_payload: dict[str, Any] | None = None,
) -> Path:
    """Write ``catalog/service_catalog.json`` under the release directory.

    When ``governed_payload`` is provided (approved independent catalog draft),
    it becomes the release authority. Otherwise rows are derived from the
    document manifest so there is still exactly one packaged catalog.
    """
    if governed_payload is not None:
        payload = validate_service_catalog_payload(
            {
                **governed_payload,
                "schemaVersion": int(
                    governed_payload.get("schemaVersion") or SERVICE_CATALOG_SCHEMA_VERSION
                ),
                "releaseId": release_id,
                "tenantId": tenant_id,
            }
        )
    else:
        payload = build_service_catalog_payload(
            manifest,
            release_id=release_id,
            tenant_id=tenant_id,
        )
    path = release_dir / SERVICE_CATALOG_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def write_service_catalog_draft(
    portal_data_dir: Path,
    *,
    tenant_id: str,
    services: list[dict[str, Any]],
    release_id: str = "draft",
) -> Path:
    """Persist a validated catalog draft outside the immutable release tree.

    This is the schema foothold for a future Portal draft→review→publish UI.
    It does **not** promote into a release or grant cloud formal write rights.
    """
    payload = validate_service_catalog_payload(
        {
            "schemaVersion": SERVICE_CATALOG_SCHEMA_VERSION,
            "releaseId": release_id,
            "tenantId": tenant_id,
            "services": services,
            "status": "DRAFT",
        }
    )
    path = portal_data_dir / SERVICE_CATALOG_DRAFT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
