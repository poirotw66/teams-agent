"""Package per-document ACL groups into a release QA sync artifact.

Chunk indexes already embed ``allowed_groups``. This thin ``acl/`` artifact
freezes the document-level audience snapshot for inventory-based GCS mirrors
so sync can verify ACL packaging independently of index bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_portal.models import ReleaseManifestEntry

ACL_ARTIFACT_RELATIVE_PATH = "acl/document_acl.json"
ACL_ARTIFACT_SCHEMA_VERSION = 1

__all__ = [
    "ACL_ARTIFACT_RELATIVE_PATH",
    "ACL_ARTIFACT_SCHEMA_VERSION",
    "build_document_acl_payload",
    "validate_document_acl_payload",
    "write_acl_artifact",
]


def validate_document_acl_payload(payload: object) -> dict[str, Any]:
    """Validate a document ACL JSON object; raise on invalid shape or fields."""
    if not isinstance(payload, dict):
        raise TypeError("Document ACL payload must be an object.")
    schema_version = payload.get("schemaVersion")
    if not isinstance(schema_version, int) or schema_version < 1:
        raise ValueError("Document ACL schemaVersion must be a positive integer.")
    release_id = payload.get("releaseId")
    if not isinstance(release_id, str) or not release_id.strip():
        raise ValueError("Document ACL releaseId is required.")
    tenant_id = payload.get("tenantId")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("Document ACL tenantId is required.")
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise TypeError("Document ACL documents must be a list.")
    for index, item in enumerate(documents):
        if not isinstance(item, dict):
            raise TypeError(f"Document ACL documents[{index}] must be an object.")
        document_id = item.get("documentId")
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError(f"Document ACL documents[{index}].documentId is required.")
        acl_groups = item.get("aclGroups")
        if not isinstance(acl_groups, list):
            raise TypeError(
                f"Document ACL documents[{index}].aclGroups must be a list."
            )
        for group_index, group in enumerate(acl_groups):
            if not isinstance(group, str) or not group.strip():
                raise ValueError(
                    f"Document ACL documents[{index}].aclGroups[{group_index}] "
                    "must be a non-empty string."
                )
    return payload


def build_document_acl_payload(
    manifest: list[ReleaseManifestEntry],
    *,
    release_id: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Derive a publishable document-ACL snapshot from release manifest entries."""
    documents: list[dict[str, Any]] = []
    for entry in manifest:
        documents.append(
            {
                "documentId": entry.document_id,
                "versionId": entry.version_id,
                "aclGroups": list(entry.acl_groups or []),
            }
        )
    return validate_document_acl_payload(
        {
            "schemaVersion": ACL_ARTIFACT_SCHEMA_VERSION,
            "releaseId": release_id,
            "tenantId": tenant_id,
            "documents": documents,
        }
    )


def write_acl_artifact(
    release_dir: Path,
    *,
    release_id: str,
    tenant_id: str,
    manifest: list[ReleaseManifestEntry],
) -> Path:
    """Write ``acl/document_acl.json`` under the release directory."""
    payload = build_document_acl_payload(
        manifest,
        release_id=release_id,
        tenant_id=tenant_id,
    )
    path = release_dir / ACL_ARTIFACT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
