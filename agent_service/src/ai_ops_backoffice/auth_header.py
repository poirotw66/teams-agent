"""Header-auth actor resolution for AI Ops Backoffice."""

from __future__ import annotations

from collections.abc import Callable

from operations_core.access import ActorContext, BackofficeRole


def resolve_header_actor(
    *,
    header_user_id: str | None,
    header_user_name: str | None,
    header_role: str | None,
    header_owner_units: str | None,
    default_owner_unit_id: str,
    header_tenant_id: str | None = None,
    header_groups: str | None = None,
    revoked: bool = False,
    auth_error_cls: type[Exception],
    header_auth_allowed_fn: Callable[[], bool],
) -> ActorContext:
    if not header_auth_allowed_fn():
        raise auth_error_cls(
            "Header auth is disabled outside dev/test. Configure ENTRA auth for production."
        )
    if not header_user_id:
        raise auth_error_cls("Missing X-Backoffice-User-Id header.")
    role = (header_role or "ANALYST").upper()
    allowed: set[BackofficeRole] = {
        "SYSTEM_ADMIN",
        "AI_ADMIN",
        "KNOWLEDGE_ADMIN",
        "SERVICE_OWNER",
        "ANALYST",
        "VIEWER",
        "AUDITOR",
    }
    if role not in allowed:
        raise auth_error_cls("Invalid backoffice role.")
    owner_units = [
        item.strip()
        for item in (header_owner_units or default_owner_unit_id).split(",")
        if item.strip()
    ]
    tenant_id = (header_tenant_id or "").strip() or "default"
    groups = tuple(
        item.strip() for item in (header_groups or "").split(",") if item.strip()
    )
    return ActorContext(
        user_id=header_user_id,
        display_name=header_user_name or header_user_id,
        role=role,  # type: ignore[arg-type]
        owner_unit_ids=tuple(owner_units),
        tenant_id=tenant_id,
        groups=groups,
        revoked=bool(revoked),
    )
