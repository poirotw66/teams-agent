from __future__ import annotations

from .models import KnowledgeDocumentRecord, PortalActor, PortalRole
from .repository import PortalNotFoundError


class PortalPermissionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


OPERATIONAL_ROLE_RANK = {
    "CONTRIBUTOR": 1,
    "REVIEWER": 2,
    "MANAGER": 3,
    "PLATFORM": 4,
}

REVIEW_ROLES: frozenset[PortalRole] = frozenset({"REVIEWER", "MANAGER", "PLATFORM"})
PUBLISH_ROLES: frozenset[PortalRole] = frozenset({"MANAGER", "PLATFORM"})
AUDIT_ROLES: frozenset[PortalRole] = frozenset({"AUDITOR", "MANAGER", "PLATFORM"})


def require_role(actor: PortalActor, *allowed: PortalRole) -> None:
    if actor.role not in allowed:
        raise PortalPermissionError(
            f"Role {actor.role} is not allowed. Required: {', '.join(allowed)}."
        )


def require_minimum_role(actor: PortalActor, minimum: PortalRole) -> None:
    if actor.role == "AUDITOR":
        raise PortalPermissionError("Auditors have read-only access.")
    if actor.role not in OPERATIONAL_ROLE_RANK:
        raise PortalPermissionError(f"Role {actor.role} is not allowed.")
    if OPERATIONAL_ROLE_RANK[actor.role] < OPERATIONAL_ROLE_RANK[minimum]:
        raise PortalPermissionError(
            f"Role {actor.role} is below the required minimum {minimum}."
        )


def can_view_document(
    actor: PortalActor,
    owner_unit_id: str,
    created_by: str,
    *,
    tenant_id: str | None = None,
) -> bool:
    if actor.role == "PLATFORM":
        return True
    if actor.tenant_id and tenant_id and actor.tenant_id != tenant_id:
        return False
    if actor.role in {"MANAGER", "REVIEWER", "CONTRIBUTOR", "AUDITOR"}:
        if actor.owner_unit_ids:
            return owner_unit_id in actor.owner_unit_ids or created_by == actor.user_id
        return True
    return False


def ensure_document_visible(
    actor: PortalActor,
    owner_unit_id: str,
    created_by: str,
    *,
    tenant_id: str | None = None,
) -> None:
    if not can_view_document(actor, owner_unit_id, created_by, tenant_id=tenant_id):
        raise PortalPermissionError("You do not have access to this document.")


def can_edit_document(
    actor: PortalActor,
    owner_unit_id: str,
    created_by: str,
    *,
    tenant_id: str | None = None,
) -> bool:
    if actor.role == "PLATFORM":
        return True
    if actor.tenant_id and tenant_id and actor.tenant_id != tenant_id:
        return False
    if actor.role in {"MANAGER", "CONTRIBUTOR"}:
        if actor.owner_unit_ids:
            return owner_unit_id in actor.owner_unit_ids or created_by == actor.user_id
        return True
    return False


def ensure_can_edit(
    actor: PortalActor,
    owner_unit_id: str,
    created_by: str,
    *,
    tenant_id: str | None = None,
) -> None:
    if not can_edit_document(actor, owner_unit_id, created_by, tenant_id=tenant_id):
        raise PortalPermissionError("You do not have permission to edit this document.")


def ensure_can_review(
    actor: PortalActor,
    submitted_by: str,
    *,
    relaxed_workflow: bool = False,
) -> None:
    if actor.role not in REVIEW_ROLES:
        raise PortalPermissionError("You do not have permission to review documents.")
    if relaxed_workflow or actor.role in {"MANAGER", "PLATFORM"}:
        return
    if actor.role == "REVIEWER" and submitted_by == actor.user_id:
        raise PortalPermissionError("Reviewers cannot approve their own submissions.")


def ensure_can_publish(actor: PortalActor) -> None:
    if actor.role not in PUBLISH_ROLES:
        raise PortalPermissionError("You do not have permission to publish documents.")


def can_view_audit(actor: PortalActor) -> bool:
    return actor.role in AUDIT_ROLES


def ensure_can_view_audit(actor: PortalActor) -> None:
    if not can_view_audit(actor):
        raise PortalPermissionError("You do not have permission to view audit events.")


def ensure_can_remove_document(
    actor: PortalActor,
    document: KnowledgeDocumentRecord,
    *,
    relaxed_workflow: bool = False,
) -> None:
    if actor.role == "PLATFORM":
        return
    if actor.role == "MANAGER":
        if (
            actor.owner_unit_ids
            and document.owner_unit_id not in actor.owner_unit_ids
            and document.created_by != actor.user_id
        ):
            raise PortalPermissionError("You do not have permission to remove this document.")
        return
    if document.status == "IN_REVIEW":
        raise PortalPermissionError("Documents in review must be decided before removal.")
    if document.current_published_version_id:
        raise PortalPermissionError("Only managers can unpublish published documents.")
    if relaxed_workflow and can_edit_document(
        actor, document.owner_unit_id, document.created_by, tenant_id=document.tenant_id
    ) and document.status in {
        "DRAFT",
        "CHANGES_REQUESTED",
        "APPROVED",
        "PUBLISH_FAILED",
    }:
        return
    raise PortalPermissionError("You do not have permission to remove this document.")


def ensure_not_found(target_type: str, target_id: str, value) -> None:
    if value is None:
        raise PortalNotFoundError(target_type, target_id)
