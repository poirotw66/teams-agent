from __future__ import annotations

import json
import logging
import os
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


@lru_cache(maxsize=8)
def _jwk_client_for_tenant(tenant_id: str) -> Any:
    from jwt import PyJWKClient

    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    return PyJWKClient(url, cache_keys=True, lifespan=300, timeout=10.0)


@lru_cache(maxsize=4)
def _jwks_for_tenant(tenant_id: str) -> dict[str, Any]:
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    return response.json()


def _resolve_signing_key(
    token: str,
    tenant_id: str,
    *,
    jwks_client: Any | None = None,
    jwks: dict[str, Any] | None = None,
) -> Any:
    try:
        import jwt
        from jwt import PyJWKSet
    except ImportError as exc:  # pragma: no cover
        raise EntraAuthError(
            "Entra auth requires PyJWT. Install teams-agent-rag-service[portal]."
        ) from exc

    if jwks is not None:
        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as exc:
            raise EntraAuthError(f"Malformed token header: {exc}") from exc
        kid = unverified_header.get("kid")
        try:
            jwk_set = PyJWKSet.from_dict(jwks)
        except Exception as exc:
            raise EntraAuthError(f"Invalid JWKS format: {exc}") from exc
        if kid:
            try:
                return jwk_set[kid].key
            except KeyError as exc:
                raise EntraAuthError(f"Signing key '{kid}' not found in JWKS.") from exc
        if len(jwk_set.keys) == 1:
            return jwk_set.keys[0].key
        raise EntraAuthError("Token header is missing 'kid' claim.")

    client = jwks_client or _jwk_client_for_tenant(tenant_id)
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        return signing_key.key
    except Exception as exc:
        raise EntraAuthError(f"Failed to resolve Entra signing key: {exc}") from exc


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
    jwks_client: Any | None = None,
    jwks: dict[str, Any] | None = None,
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

        if not tenant_id or not client_id:
            raise EntraAuthError("Entra tenant_id and client_id are required.")

        signing_key = _resolve_signing_key(
            token,
            tenant_id,
            jwks_client=jwks_client,
            jwks=jwks,
        )
        issuers = [
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://sts.windows.net/{tenant_id}/",
        ]
        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=issuers,
                options={"verify_aud": True, "verify_signature": True},
            )
        except jwt.PyJWTError as exc:
            raise EntraAuthError(f"Token validation failed: {exc}") from exc
    else:
        environment = (
            os.environ.get("AGENT_DEPLOYMENT_ENV")
            or os.environ.get("RAG_DEPLOYMENT_ENV")
            or "dev"
        ).lower()
        if environment not in {"dev", "test", "poc"}:
            raise EntraAuthError("Token signature validation cannot be disabled in production.")
        claims = _decode_unverified_claims(token)

    user_id = str(claims.get("oid") or claims.get("sub") or "")
    if not user_id:
        raise EntraAuthError("Token is missing oid/sub claim.")
    display_name = str(claims.get("name") or claims.get("preferred_username") or user_id)

    role = _resolve_role(claims)
    owner_units = _resolve_owner_units(claims, default_owner_unit_id)
    claim_tenant = str(claims.get("tid") or tenant_id or "").strip() or None
    return ActorContext(
        user_id=user_id,
        display_name=display_name,
        role=role,
        owner_unit_ids=tuple(owner_units),
        tenant_id=claim_tenant,
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
