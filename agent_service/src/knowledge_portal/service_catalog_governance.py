"""Enterprise service-catalog draft governance (spec §2.3).

Persists catalog rows separately from document drafts via a pluggable
``CatalogDraftStore`` (FILE local-dev fallback, FIRESTORE multi-instance, or
in-memory for tests). Approved catalogs are packaged into immutable releases
via ``write_service_catalog_artifact`` / finalize. Console-v2 edits via BFF
``/api/knowledge/catalog*``. Approve/reject reuse ``ensure_can_review`` SoD
(submitter≠approver unless PLATFORM / relaxed).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from knowledge_portal.service_catalog_artifact import (
    SERVICE_CATALOG_DRAFT_RELATIVE_PATH,
    SERVICE_CATALOG_SCHEMA_VERSION,
    validate_service_catalog_payload,
)
from knowledge_portal.service_catalog_draft_store import (
    CatalogDraftStore,
    FileCatalogDraftStore,
)

CatalogStatus = Literal["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED"]

_ALLOWED_TRANSITIONS: dict[CatalogStatus, frozenset[CatalogStatus]] = {
    "DRAFT": frozenset({"IN_REVIEW"}),
    "IN_REVIEW": frozenset({"APPROVED", "REJECTED", "DRAFT"}),
    "APPROVED": frozenset({"DRAFT"}),  # reopen for edits
    "REJECTED": frozenset({"DRAFT"}),
}


class ServiceCatalogGovernanceError(Exception):
    """Raised for invalid catalog draft transitions or link rules."""

    def __init__(self, message: str, *, code: str = "CATALOG_GOVERNANCE_ERROR") -> None:
        super().__init__(message)
        self.code = code


def catalog_draft_path(data_dir: Path, *, tenant_id: str) -> Path:
    safe_tenant = tenant_id.strip().replace("/", "_") or "default"
    return data_dir / "tenants" / safe_tenant / SERVICE_CATALOG_DRAFT_RELATIVE_PATH


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_store(
    data_dir: Path,
    store: CatalogDraftStore | None,
) -> CatalogDraftStore:
    return store if store is not None else FileCatalogDraftStore(data_dir)


def _normalize_service_row(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    service_id = str(item.get("serviceId") or "").strip()
    if not service_id:
        raise ServiceCatalogGovernanceError(
            f"services[{index}].serviceId is required.",
            code="CATALOG_SERVICE_ID_REQUIRED",
        )
    document_id = str(item.get("documentId") or item.get("linkedDocumentId") or "").strip()
    if not document_id:
        raise ServiceCatalogGovernanceError(
            f"services[{index}] must link an approved document "
            f"(documentId) for service '{service_id}'.",
            code="CATALOG_DOCUMENT_LINK_REQUIRED",
        )
    aliases = [str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip()]
    official = str(item.get("officialName") or service_id).strip()
    version_id = item.get("versionId")
    return {
        "serviceId": service_id,
        "officialName": official,
        "aliases": aliases,
        "documentId": document_id,
        "versionId": str(version_id).strip() if version_id else None,
        "sourcePath": item.get("sourcePath"),
        "aclGroups": list(item.get("aclGroups") or item.get("audienceGroupIds") or []),
        "ownerUnitId": item.get("ownerUnitId"),
    }


def assert_services_link_published_documents(
    services: list[dict[str, Any]],
    *,
    published_document_ids: set[str],
) -> None:
    """Fail closed when a catalog row does not link a published retrievable doc."""
    if not services:
        raise ServiceCatalogGovernanceError(
            "Service catalog must contain at least one service entry.",
            code="CATALOG_EMPTY",
        )
    for index, item in enumerate(services):
        document_id = str(item.get("documentId") or "").strip()
        if document_id not in published_document_ids:
            raise ServiceCatalogGovernanceError(
                f"services[{index}] documentId '{document_id}' is not an "
                "approved published document in the release set.",
                code="CATALOG_DOCUMENT_NOT_PUBLISHED",
            )


def load_catalog_draft(
    data_dir: Path,
    *,
    tenant_id: str,
    store: CatalogDraftStore | None = None,
) -> dict[str, Any] | None:
    resolved = _resolve_store(data_dir, store)
    try:
        payload = resolved.load(tenant_id)
    except TypeError as error:
        raise ServiceCatalogGovernanceError(
            "Catalog draft is corrupt.",
            code="CATALOG_DRAFT_CORRUPT",
        ) from error
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ServiceCatalogGovernanceError(
            "Catalog draft is corrupt.",
            code="CATALOG_DRAFT_CORRUPT",
        )
    return payload


def save_catalog_draft(
    data_dir: Path,
    *,
    tenant_id: str,
    services: list[dict[str, Any]],
    status: CatalogStatus = "DRAFT",
    actor_id: str | None = None,
    reason: str | None = None,
    published_document_ids: set[str] | None = None,
    store: CatalogDraftStore | None = None,
) -> dict[str, Any]:
    """Persist a catalog draft. When approving, ``published_document_ids`` is required."""
    normalized = [
        _normalize_service_row(item, index=index)
        for index, item in enumerate(services)
        if isinstance(item, dict)
    ]
    if status == "APPROVED":
        if published_document_ids is None:
            raise ServiceCatalogGovernanceError(
                "Approving a catalog requires the published document id set.",
                code="CATALOG_PUBLISHED_SET_REQUIRED",
            )
        assert_services_link_published_documents(
            normalized,
            published_document_ids=published_document_ids,
        )
    payload = validate_service_catalog_payload(
        {
            "schemaVersion": SERVICE_CATALOG_SCHEMA_VERSION,
            "releaseId": "draft",
            "tenantId": tenant_id,
            "services": normalized,
            "status": status,
            "updatedAt": _utc_now_iso(),
            "updatedBy": actor_id,
            "reason": reason,
        }
    )
    _resolve_store(data_dir, store).save(tenant_id, payload)
    return payload


def transition_catalog_draft(
    data_dir: Path,
    *,
    tenant_id: str,
    target_status: CatalogStatus,
    actor_id: str,
    reason: str | None = None,
    published_document_ids: set[str] | None = None,
    store: CatalogDraftStore | None = None,
) -> dict[str, Any]:
    current = load_catalog_draft(data_dir, tenant_id=tenant_id, store=store)
    if current is None:
        raise ServiceCatalogGovernanceError(
            "No catalog draft exists for this tenant.",
            code="CATALOG_DRAFT_MISSING",
        )
    current_status = str(current.get("status") or "DRAFT").upper()
    if current_status not in _ALLOWED_TRANSITIONS:
        raise ServiceCatalogGovernanceError(
            f"Unknown catalog status '{current_status}'.",
            code="CATALOG_STATUS_INVALID",
        )
    allowed = _ALLOWED_TRANSITIONS[current_status]  # type: ignore[index]
    if target_status not in allowed:
        raise ServiceCatalogGovernanceError(
            f"Cannot transition catalog from {current_status} to {target_status}.",
            code="CATALOG_TRANSITION_DENIED",
        )
    services = current.get("services")
    if not isinstance(services, list):
        raise ServiceCatalogGovernanceError(
            "Catalog draft services are invalid.",
            code="CATALOG_DRAFT_CORRUPT",
        )
    return save_catalog_draft(
        data_dir,
        tenant_id=tenant_id,
        services=[item for item in services if isinstance(item, dict)],
        status=target_status,
        actor_id=actor_id,
        reason=reason,
        published_document_ids=published_document_ids,
        store=store,
    )


def load_approved_catalog_for_release(
    data_dir: Path,
    *,
    tenant_id: str,
    release_id: str,
    published_document_ids: set[str],
    store: CatalogDraftStore | None = None,
) -> dict[str, Any] | None:
    """Return an APPROVED catalog payload remapped to ``release_id``, or None."""
    draft = load_catalog_draft(data_dir, tenant_id=tenant_id, store=store)
    if draft is None:
        return None
    if str(draft.get("status") or "").upper() != "APPROVED":
        return None
    services = draft.get("services")
    if not isinstance(services, list):
        return None
    normalized = [item for item in services if isinstance(item, dict)]
    assert_services_link_published_documents(
        normalized,
        published_document_ids=published_document_ids,
    )
    return validate_service_catalog_payload(
        {
            "schemaVersion": int(draft.get("schemaVersion") or SERVICE_CATALOG_SCHEMA_VERSION),
            "releaseId": release_id,
            "tenantId": tenant_id,
            "services": normalized,
            "status": "APPROVED",
            "source": "governed_catalog_draft",
        }
    )


__all__ = [
    "CatalogStatus",
    "ServiceCatalogGovernanceError",
    "assert_services_link_published_documents",
    "catalog_draft_path",
    "load_approved_catalog_for_release",
    "load_catalog_draft",
    "save_catalog_draft",
    "transition_catalog_draft",
]
