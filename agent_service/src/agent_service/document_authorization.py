"""Unified Document Authorization Layer.

Enforces cross-tenant isolation, department/owner unit boundaries, ACL group membership,
revocation policies, and archival/deletion states across all document and source entry points
as required by F02 and A04.
"""

from __future__ import annotations

from typing import Any
from ai_ops_backoffice.services.source_models import DocumentAccessDecision


class DocumentAccessDeniedError(Exception):
    """Standardized safe error raised when document access is denied.

    Maintains safe error responses without leaking the existence, filename, or
    metadata of restricted documents.
    """

    def __init__(
        self,
        status_code: int = 404,
        detail: str = "Source reference not found or access denied.",
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _extract_attr(target: Any, attr: str, default: Any = None) -> Any:
    if isinstance(target, dict):
        return target.get(attr, default)
    return getattr(target, attr, default)


def authorize_document_access(
    actor: Any,
    document: Any,
    action: str = "read",
) -> DocumentAccessDecision:
    """Evaluate unified access control policy for a document or source record.

    Args:
        actor: Authenticated actor context (OpsActor, PortalActor, or dict).
        document: Document target (SourceRecord, KnowledgeVersionRecord, KnowledgeDocumentRecord, or dict).
        action: Requested action ('read', 'preview', 'download', 'edit', 'publish').

    Returns:
        DocumentAccessDecision indicating allowed status and safe reason.
    """
    if actor is None or document is None:
        return DocumentAccessDecision(
            allowed=False,
            reason="Actor or document reference is missing.",
            status_code=404,
            safe_error_code="NOT_FOUND",
        )

    # 1. Revocation check
    is_revoked = bool(
        _extract_attr(actor, "revoked", False)
        or _extract_attr(actor, "is_revoked", False)
        or _extract_attr(actor, "active", True) is False
    )
    if is_revoked:
        return DocumentAccessDecision(
            allowed=False,
            reason="Actor credentials or permissions have been revoked.",
            status_code=403,
            safe_error_code="REVOKED",
        )

    # 2. Tenant isolation check
    actor_tenant_id = _extract_attr(actor, "tenant_id")
    doc_tenant_id = _extract_attr(document, "tenant_id")
    if actor_tenant_id and doc_tenant_id and str(actor_tenant_id) != str(doc_tenant_id):
        # Strict isolation: tenant mismatch returns 404 to avoid leaking existence
        return DocumentAccessDecision(
            allowed=False,
            reason="Cross-tenant access prohibited.",
            status_code=404,
            safe_error_code="TENANT_MISMATCH",
        )

    # 3. Deletion and Archival checks
    is_deleted = bool(_extract_attr(document, "is_deleted", False))
    if is_deleted:
        return DocumentAccessDecision(
            allowed=False,
            reason="Document has been deleted under retention policy.",
            status_code=404,
            safe_error_code="DELETED",
        )

    is_archived = bool(_extract_attr(document, "is_archived", False))
    actor_capabilities = set(_extract_attr(actor, "capabilities", []))
    actor_role = str(_extract_attr(actor, "role", "")).upper()
    if is_archived:
        can_read_archive = (
            "ops.archive.read" in actor_capabilities
            or actor_role == "PLATFORM"
        )
        if not can_read_archive:
            return DocumentAccessDecision(
                allowed=False,
                reason="Document is archived.",
                status_code=404,
                safe_error_code="ARCHIVED",
            )

    # 4. Role, Unit, and ACL checks
    if actor_role == "PLATFORM":
        # Platform administrators have tenant-scoped superuser read access
        return DocumentAccessDecision(
            allowed=True,
            reason="Platform superuser access granted.",
            status_code=200,
            safe_error_code="ACCESS_GRANTED",
        )

    actor_user_id = str(_extract_attr(actor, "user_id", ""))
    doc_created_by = _extract_attr(document, "created_by")
    is_creator = bool(doc_created_by and str(doc_created_by) == actor_user_id)

    # Check department / owner unit boundary
    doc_owner_unit = _extract_attr(document, "owner_unit_id")
    actor_owner_units = set(_extract_attr(actor, "owner_unit_ids", []))
    if doc_owner_unit:
        unit_match = str(doc_owner_unit) in actor_owner_units
        cross_unit_read = (
            actor_role in {"AUDITOR", "MANAGER"}
            or "ops.documents.read_all" in actor_capabilities
        )
        if not (unit_match or is_creator or cross_unit_read):
            return DocumentAccessDecision(
                allowed=False,
                reason="Actor does not belong to the document owner unit.",
                status_code=404,
                safe_error_code="UNIT_MISMATCH",
            )

    # Check ACL group restrictions
    doc_acl_groups = list(_extract_attr(document, "acl_groups", []))
    if doc_acl_groups:
        actor_groups = set(_extract_attr(actor, "groups", []))
        group_match = bool(actor_groups.intersection(doc_acl_groups))
        if not (group_match or is_creator):
            return DocumentAccessDecision(
                allowed=False,
                reason="Actor is not a member of required ACL groups.",
                status_code=404,
                safe_error_code="ACL_DENIED",
            )

    return DocumentAccessDecision(
        allowed=True,
        reason="Access authorized under unified policy.",
        status_code=200,
        safe_error_code="ACCESS_GRANTED",
    )


def ensure_document_access(
    actor: Any,
    document: Any,
    action: str = "read",
) -> DocumentAccessDecision:
    """Verify document access and raise safe DocumentAccessDeniedError on denial."""
    decision = authorize_document_access(actor, document, action=action)
    if not decision.allowed:
        raise DocumentAccessDeniedError(
            status_code=decision.status_code,
            detail="Source reference not found or access denied.",
        )
    return decision
