from __future__ import annotations

from .models import PortalActor, RoleCapabilities
from .rbac import AUDIT_ROLES, PUBLISH_ROLES, REVIEW_ROLES, PortalPermissionError

CREATE_DOCUMENT_ROLES = frozenset({"CONTRIBUTOR", "MANAGER", "PLATFORM"})
LIST_RELEASES_ROLES = frozenset({"MANAGER", "PLATFORM"})


def role_capabilities(actor: PortalActor) -> RoleCapabilities:
    role = actor.role
    return RoleCapabilities(
        create_document=role in CREATE_DOCUMENT_ROLES,
        import_markdown=role in CREATE_DOCUMENT_ROLES,
        list_pending_reviews=role in REVIEW_ROLES,
        decide_review=role in REVIEW_ROLES,
        publish=role in PUBLISH_ROLES,
        list_releases=role in LIST_RELEASES_ROLES,
        manage_releases=role in PUBLISH_ROLES,
        view_audit=role in AUDIT_ROLES,
    )


def ensure_can_create_document(actor: PortalActor) -> None:
    if actor.role not in CREATE_DOCUMENT_ROLES:
        raise PortalPermissionError("You do not have permission to create documents.")


def ensure_can_import_markdown(actor: PortalActor) -> None:
    if actor.role not in CREATE_DOCUMENT_ROLES:
        raise PortalPermissionError("You do not have permission to import documents.")


def ensure_can_list_pending_reviews(actor: PortalActor) -> None:
    if actor.role not in REVIEW_ROLES:
        raise PortalPermissionError("You do not have permission to view pending reviews.")


def ensure_can_list_releases(actor: PortalActor) -> None:
    if actor.role not in LIST_RELEASES_ROLES:
        raise PortalPermissionError("You do not have permission to view release history.")
