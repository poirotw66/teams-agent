from __future__ import annotations

import os

from operations_core.access import ActorContext

from .auth_header import resolve_header_actor
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
    header_groups: str | None = None,
    revoked: bool = False,
) -> ActorContext:
    mode = auth_mode.upper()
    if mode == "ENTRA":
        if not entra_tenant_id or not entra_client_id:
            raise BackofficeAuthError("Entra tenant/client configuration is required.")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise BackofficeAuthError("Missing Entra bearer token.")
        environment = (
            os.environ.get("AGENT_DEPLOYMENT_ENV")
            or os.environ.get("RAG_DEPLOYMENT_ENV")
            or "dev"
        ).lower()
        if environment in {"dev", "test", "poc"}:
            validate_signature = os.environ.get(
                "AI_OPS_ENTRA_VALIDATE_JWT", "true"
            ).lower() in {"1", "true", "yes", "on"}
        else:
            validate_signature = True
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

    return resolve_header_actor(
        header_user_id=header_user_id,
        header_user_name=header_user_name,
        header_role=header_role,
        header_owner_units=header_owner_units,
        default_owner_unit_id=default_owner_unit_id,
        header_tenant_id=header_tenant_id,
        header_groups=header_groups,
        revoked=revoked,
        auth_error_cls=BackofficeAuthError,
        header_auth_allowed_fn=header_auth_allowed,
    )
