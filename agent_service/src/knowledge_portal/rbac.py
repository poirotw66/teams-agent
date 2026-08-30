from __future__ import annotations

from .models import PortalActor, PortalRole
from .repository import PortalNotFoundError


class PortalPermissionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


ROLE_RANK = {
    "CONTRIBUTOR": 1,
    "REVIEWER": 2,
    "MANAGER": 3,
    "PLATFORM": 4,
    "AUDITOR": 5,
}


def require_role(actor: PortalActor, *allowed: PortalRole) -> None:
    if actor.role not in allowed:
        raise PortalPermissionError(
            f"Role {actor.role} is not allowed. Required: {', '.join(allowed)}."
        )


def require_minimum_role(actor: PortalActor, minimum: PortalRole) -> None:
    if ROLE_RANK[actor.role] < ROLE_RANK[minimum]:
        raise PortalPermissionError(
            f"Role {actor.role} is below the required minimum {minimum}."
        )


def can_view_document(actor: PortalActor, owner_unit_id: str, created_by: str) -> bool:
    if actor.role in {"MANAGER", "PLATFORM", "AUDITOR", "REVIEWER"}:
        return True
    if actor.role == "CONTRIBUTOR":
        return (
            owner_unit_id in actor.owner_unit_ids or created_by == actor.user_id
        )
    return False


def ensure_document_visible(actor: PortalActor, owner_unit_id: str, created_by: str) -> None:
    if not can_view_document(actor, owner_unit_id, created_by):
        raise PortalPermissionError("You do not have access to this document.")


def can_edit_document(actor: PortalActor, owner_unit_id: str, created_by: str) -> bool:
    if actor.role in {"MANAGER", "PLATFORM"}:
        return True
    if actor.role == "CONTRIBUTOR":
        return (
            owner_unit_id in actor.owner_unit_ids or created_by == actor.user_id
        )
    return False


def ensure_can_edit(actor: PortalActor, owner_unit_id: str, created_by: str) -> None:
    if not can_edit_document(actor, owner_unit_id, created_by):
        raise PortalPermissionError("You do not have permission to edit this document.")


def ensure_can_review(actor: PortalActor, submitted_by: str) -> None:
    require_minimum_role(actor, "REVIEWER")
    if actor.role == "REVIEWER" and submitted_by == actor.user_id:
        raise PortalPermissionError("Reviewers cannot approve their own submissions.")


def ensure_can_publish(actor: PortalActor) -> None:
    require_minimum_role(actor, "MANAGER")


def ensure_not_found(target_type: str, target_id: str, value) -> None:
    if value is None:
        raise PortalNotFoundError(target_type, target_id)
