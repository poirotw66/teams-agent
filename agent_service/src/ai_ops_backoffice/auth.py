from __future__ import annotations

import os

from agent_service.operations.access import ActorContext, BackofficeRole

from .entra_auth import EntraAuthError, resolve_actor_from_entra


class BackofficeAuthError(Exception):
    pass


def header_auth_allowed() -> bool:
    environment = (
        os.environ.get("AGENT_DEPLOYMENT_ENV")
        or os.environ.get("RAG_DEPLOYMENT_ENV")
        or "dev"
    ).lower()
    if environment in {"dev", "test", "poc"}:
        return True
    return os.environ.get("AI_OPS_BACKOFFICE_ALLOW_HEADER_AUTH", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def resolve_actor(
    *,
    auth_mode: str,
    authorization: str | None,
    header_user_id: str | None,
    header_user_name: str | None,
    header_role: str | None,
    header_owner_units: str | None,
    default_owner_unit_id: str,
    entra_tenant_id: str | None,
    entra_client_id: str | None,
    header_tenant_id: str | None = None,
) -> ActorContext:
    mode = auth_mode.upper()
    if mode == "ENTRA":
        if not entra_tenant_id or not entra_client_id:
            raise BackofficeAuthError("Entra tenant/client configuration is required.")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise BackofficeAuthError("Missing Entra bearer token.")
        validate_signature = os.environ.get("AI_OPS_ENTRA_VALIDATE_JWT", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            return resolve_actor_from_entra(
                token,
                tenant_id=entra_tenant_id,
                client_id=entra_client_id,
                default_owner_unit_id=default_owner_unit_id,
                validate_signature=validate_signature,
            )
        except EntraAuthError as exc:
            raise BackofficeAuthError(str(exc)) from exc

    if not header_auth_allowed():
        raise BackofficeAuthError(
            "Header auth is disabled outside dev/test. Configure ENTRA auth for production."
        )
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
    tenant_id = (header_tenant_id or "").strip() or "local-development"
    return ActorContext(
        user_id=header_user_id,
        display_name=header_user_name or header_user_id,
        role=role,  # type: ignore[arg-type]
        owner_unit_ids=tuple(owner_units),
        tenant_id=tenant_id,
    )
