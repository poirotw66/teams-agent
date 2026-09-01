from __future__ import annotations

from agent_service.operations.access import ActorContext, BackofficeRole


class BackofficeAuthError(Exception):
    pass


def resolve_actor(
    *,
    auth_mode: str,
    header_user_id: str | None,
    header_user_name: str | None,
    header_role: str | None,
    header_owner_units: str | None,
    default_owner_unit_id: str,
) -> ActorContext:
    if auth_mode == "ENTRA":
        raise BackofficeAuthError("Entra auth for AI Ops Backoffice is not configured in LAB.")
    if not header_user_id:
        raise BackofficeAuthError("Missing X-Backoffice-User-Id header.")
    role = (header_role or "ANALYST").upper()
    allowed: set[BackofficeRole] = {
        "SYSTEM_ADMIN",
        "AI_ADMIN",
        "KNOWLEDGE_ADMIN",
        "SERVICE_OWNER",
        "ANALYST",
        "AUDITOR",
    }
    if role not in allowed:
        raise BackofficeAuthError("Invalid backoffice role.")
    owner_units = [
        item.strip()
        for item in (header_owner_units or default_owner_unit_id).split(",")
        if item.strip()
    ]
    return ActorContext(
        user_id=header_user_id,
        display_name=header_user_name or header_user_id,
        role=role,  # type: ignore[arg-type]
        owner_unit_ids=tuple(owner_units),
    )
