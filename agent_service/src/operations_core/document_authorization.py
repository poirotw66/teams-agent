"""Unified document authorization helpers shared by Agent and Backoffice.

Enforces cross-tenant isolation, department/owner unit boundaries, ACL group
membership, revocation policies, and archival/deletion states across document
and source entry points (F02 / A04).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DocumentAccessDecision(BaseModel):
    """Result of unified document authorization evaluation."""

    allowed: bool
    reason: str
    status_code: int = 200
    safe_error_code: str = "ACCESS_GRANTED"


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


def _denied(
    reason: str,
    *,
    status_code: int,
    safe_error_code: str,
) -> DocumentAccessDecision:
    return DocumentAccessDecision(
        allowed=False,
        reason=reason,
        status_code=status_code,
        safe_error_code=safe_error_code,
    )


def _granted(reason: str) -> DocumentAccessDecision:
    return DocumentAccessDecision(
        allowed=True,
        reason=reason,
        status_code=200,
        safe_error_code="ACCESS_GRANTED",
    )


def _check_actor_revoked(actor: Any) -> DocumentAccessDecision | None:
    is_revoked = bool(
        _extract_attr(actor, "revoked", False)
        or _extract_attr(actor, "is_revoked", False)
        or _extract_attr(actor, "active", True) is False
    )
    if not is_revoked:
        return None
    return _denied(
        "Actor credentials or permissions have been revoked.",
        status_code=403,
        safe_error_code="REVOKED",
    )


def _check_tenant_isolation(actor: Any, document: Any) -> DocumentAccessDecision | None:
    actor_tenant_id = _extract_attr(actor, "tenant_id")
    doc_tenant_id = _extract_attr(document, "tenant_id")
    if not (actor_tenant_id and doc_tenant_id and str(actor_tenant_id) != str(doc_tenant_id)):
        return None
    # Strict isolation: tenant mismatch returns 404 to avoid leaking existence
    return _denied(
        "Cross-tenant access prohibited.",
        status_code=404,
        safe_error_code="TENANT_MISMATCH",
    )


def _check_document_lifecycle(
    document: Any,
    *,
    actor_capabilities: set[Any],
    actor_role: str,
) -> DocumentAccessDecision | None:
    if bool(_extract_attr(document, "is_deleted", False)):
        return _denied(
            "Document has been deleted under retention policy.",
            status_code=404,
            safe_error_code="DELETED",
        )
    if not bool(_extract_attr(document, "is_archived", False)):
        return None
    can_read_archive = (
        "ops.archive.read" in actor_capabilities or actor_role == "PLATFORM"
    )
    if can_read_archive:
        return None
    return _denied(
        "Document is archived.",
        status_code=404,
        safe_error_code="ARCHIVED",
    )


def _check_owner_unit_boundary(
    actor: Any,
    document: Any,
    *,
    actor_role: str,
    actor_capabilities: set[Any],
    is_creator: bool,
) -> DocumentAccessDecision | None:
    doc_owner_unit = _extract_attr(document, "owner_unit_id")
    if not doc_owner_unit:
        return None
    actor_owner_units = set(_extract_attr(actor, "owner_unit_ids", []))
    unit_match = str(doc_owner_unit) in actor_owner_units
    cross_unit_read = (
        actor_role in {"AUDITOR", "MANAGER"}
        or "ops.documents.read_all" in actor_capabilities
    )
    if unit_match or is_creator or cross_unit_read:
        return None
    return _denied(
        "Actor does not belong to the document owner unit.",
        status_code=404,
        safe_error_code="UNIT_MISMATCH",
    )


def _check_acl_groups(
    actor: Any,
    document: Any,
    *,
    actor_role: str,
    is_creator: bool,
) -> DocumentAccessDecision | None:
    # Admin/audit roles already bypass owner-unit boundaries and must also be
    # able to open cited originals for ops review without requiring every
    # console session to mint document ACL groups.
    doc_acl_groups = list(_extract_attr(document, "acl_groups", []))
    if not doc_acl_groups:
        return None
    actor_groups = set(_extract_attr(actor, "groups", []))
    group_match = bool(actor_groups.intersection(doc_acl_groups))
    admin_bypass = actor_role in {
        "SYSTEM_ADMIN",
        "AI_ADMIN",
        "AUDITOR",
        "KNOWLEDGE_ADMIN",
    }
    if group_match or is_creator or admin_bypass:
        return None
    return _denied(
        "Actor is not a member of required ACL groups.",
        status_code=404,
        safe_error_code="ACL_DENIED",
    )


def authorize_document_access(
    actor: Any,
    document: Any,
    action: str = "read",
) -> DocumentAccessDecision:
    """Evaluate unified access control policy for a document or source record.

    Args:
        actor: Authenticated actor context (OpsActor, PortalActor, or dict).
        document: Document target (SourceRecord, KnowledgeVersionRecord,
            KnowledgeDocumentRecord, or dict).
        action: Requested action ('read', 'preview', 'download', 'edit', 'publish').

    Returns:
        DocumentAccessDecision indicating allowed status and safe reason.
    """
    _ = action  # Reserved for future action-specific policy branches.
    if actor is None or document is None:
        return _denied(
            "Actor or document reference is missing.",
            status_code=404,
            safe_error_code="NOT_FOUND",
        )

    revoked = _check_actor_revoked(actor)
    if revoked is not None:
        return revoked

    tenant_denied = _check_tenant_isolation(actor, document)
    if tenant_denied is not None:
        return tenant_denied

    actor_capabilities = set(_extract_attr(actor, "capabilities", []))
    actor_role = str(_extract_attr(actor, "role", "")).upper()

    lifecycle_denied = _check_document_lifecycle(
        document,
        actor_capabilities=actor_capabilities,
        actor_role=actor_role,
    )
    if lifecycle_denied is not None:
        return lifecycle_denied

    if actor_role == "PLATFORM":
        return _granted("Platform superuser access granted.")

    actor_user_id = str(_extract_attr(actor, "user_id", ""))
    doc_created_by = _extract_attr(document, "created_by")
    is_creator = bool(doc_created_by and str(doc_created_by) == actor_user_id)

    unit_denied = _check_owner_unit_boundary(
        actor,
        document,
        actor_role=actor_role,
        actor_capabilities=actor_capabilities,
        is_creator=is_creator,
    )
    if unit_denied is not None:
        return unit_denied

    acl_denied = _check_acl_groups(
        actor,
        document,
        actor_role=actor_role,
        is_creator=is_creator,
    )
    if acl_denied is not None:
        return acl_denied

    return _granted("Access authorized under unified policy.")


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
