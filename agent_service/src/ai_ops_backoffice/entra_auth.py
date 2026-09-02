from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

import httpx

from agent_service.operations.access import ActorContext, BackofficeRole

logger = logging.getLogger(__name__)

ROLE_CLAIM = "roles"
GROUP_ROLE_MAPPING: dict[str, BackofficeRole] = {
    "AI_OPS_SYSTEM_ADMIN": "SYSTEM_ADMIN",
    "AI_OPS_AI_ADMIN": "AI_ADMIN",
    "AI_OPS_KNOWLEDGE_ADMIN": "KNOWLEDGE_ADMIN",
    "AI_OPS_SERVICE_OWNER": "SERVICE_OWNER",
    "AI_OPS_ANALYST": "ANALYST",
    "AI_OPS_AUDITOR": "AUDITOR",
}


class EntraAuthError(Exception):
    pass


@lru_cache(maxsize=4)
def _jwks_for_tenant(tenant_id: str) -> dict[str, Any]:
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    return response.json()


def _decode_unverified_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise EntraAuthError("Invalid bearer token format.")
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    decoded = json.loads(
        __import__("base64").urlsafe_b64decode(payload + padding).decode("utf-8")
    )
    if not isinstance(decoded, dict):
        raise EntraAuthError("Invalid bearer token payload.")
    return decoded


def resolve_actor_from_entra(
    bearer_token: str,
    *,
    tenant_id: str,
    client_id: str,
    default_owner_unit_id: str,
    validate_signature: bool = True,
) -> ActorContext:
    token = bearer_token.strip()
    if not token:
        raise EntraAuthError("Missing bearer token.")

    if validate_signature:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover
            raise EntraAuthError(
                "Entra auth requires PyJWT. Install teams-agent-rag-service[portal]."
            ) from exc
        jwks = _jwks_for_tenant(tenant_id)
        issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=client_id,
            issuer=issuer,
            options={"verify_aud": True},
        )
    else:
        claims = _decode_unverified_claims(token)

    user_id = str(claims.get("oid") or claims.get("sub") or "")
    if not user_id:
        raise EntraAuthError("Token is missing oid/sub claim.")
    display_name = str(claims.get("name") or claims.get("preferred_username") or user_id)

    role = _resolve_role(claims)
    owner_units = _resolve_owner_units(claims, default_owner_unit_id)
    return ActorContext(
        user_id=user_id,
        display_name=display_name,
        role=role,
        owner_unit_ids=tuple(owner_units),
    )


def _resolve_role(claims: dict[str, Any]) -> BackofficeRole:
    app_roles = claims.get(ROLE_CLAIM) or claims.get("roles") or []
    if isinstance(app_roles, str):
        app_roles = [app_roles]
    for item in app_roles:
        mapped = GROUP_ROLE_MAPPING.get(str(item))
        if mapped:
            return mapped
    groups = claims.get("groups") or []
    if isinstance(groups, str):
        groups = [groups]
    for item in groups:
        mapped = GROUP_ROLE_MAPPING.get(str(item))
        if mapped:
            return mapped
    return "ANALYST"


def _resolve_owner_units(claims: dict[str, Any], default_owner_unit_id: str) -> list[str]:
    raw = claims.get("owner_units") or claims.get("extension_owner_units")
    if isinstance(raw, str):
        units = [part.strip() for part in raw.split(",") if part.strip()]
        if units:
            return units
    if isinstance(raw, list):
        units = [str(item).strip() for item in raw if str(item).strip()]
        if units:
            return units
    return [default_owner_unit_id]
