from __future__ import annotations

import hmac
import logging
from typing import Any
from urllib.parse import unquote

import httpx

from .draft_retrieval import DraftSearchResult
from .models import PortalActor, PortalRole
from .settings import PortalSettings

logger = logging.getLogger(__name__)


class PortalAuthError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def decode_portal_header_value(value: str) -> str:
    """Decode percent-encoded portal header values from browser fetch()."""
    return unquote(value)


def _header_actor(
    *,
    user_id: str,
    display_name: str,
    role: str,
    owner_units: list[str],
) -> PortalActor:
    if role not in {"CONTRIBUTOR", "REVIEWER", "MANAGER", "PLATFORM", "AUDITOR"}:
        raise PortalAuthError("Invalid portal role.")
    return PortalActor(
        user_id=user_id,
        display_name=display_name,
        role=role,  # type: ignore[arg-type]
        owner_unit_ids=owner_units,
    )


def _role_from_claims(claims: dict[str, Any], settings: PortalSettings) -> PortalRole:
    token_roles = {str(item) for item in claims.get("roles") or []}
    for role_name, configured in (
        ("PLATFORM", settings.entra_platform_roles),
        ("MANAGER", settings.entra_manager_roles),
        ("REVIEWER", settings.entra_reviewer_roles),
        ("AUDITOR", settings.entra_auditor_roles),
    ):
        if token_roles.intersection(configured):
            return role_name  # type: ignore[return-value]
    return "CONTRIBUTOR"


def _validate_entra_token(token: str, settings: PortalSettings) -> PortalActor:
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as exc:
        raise PortalAuthError(
            "Entra auth requires PyJWT. Install with: uv sync --extra portal"
        ) from exc

    if not settings.entra_tenant_id or not settings.entra_client_id:
        raise PortalAuthError("ENTRA tenant/client settings are required.")

    issuer = f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0"
    jwks_url = f"https://login.microsoftonline.com/{settings.entra_tenant_id}/discovery/v2.0/keys"
    jwks_client = PyJWKClient(jwks_url)
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.entra_allowed_audiences or [settings.entra_client_id],
        issuer=issuer,
    )
    user_id = str(claims.get("oid") or claims.get("sub") or "")
    display_name = str(claims.get("name") or claims.get("preferred_username") or user_id)
    if not user_id:
        raise PortalAuthError("Entra token is missing oid/sub.")
    return PortalActor(
        user_id=user_id,
        display_name=display_name,
        role=_role_from_claims(claims, settings),
        owner_unit_ids=list(settings.default_owner_unit_ids),
    )


def resolve_portal_actor(
    *,
    settings: PortalSettings,
    authorization: str | None,
    header_user_id: str | None,
    header_user_name: str | None,
    header_role: str | None,
    header_owner_units: str | None,
    delegation_header: str | None = None,
) -> PortalActor:
    # Prefer signed BFF delegation over browser X-Portal-* headers.
    if delegation_header:
        return _actor_from_delegation(
            settings=settings,
            authorization=authorization,
            delegation_header=delegation_header,
        )

    if settings.auth_mode == "ENTRA":
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise PortalAuthError("Entra auth requires Authorization: Bearer <token>.")
        return _validate_entra_token(token, settings)

    if not header_user_id or not header_user_name:
        raise PortalAuthError(
            "Missing portal identity headers. Use Entra auth, BFF delegation, "
            "or X-Portal-* headers in isolated local mode."
        )
    owner_units = [
        item.strip()
        for item in (header_owner_units or ",".join(settings.default_owner_unit_ids)).split(",")
        if item.strip()
    ]
    return _header_actor(
        user_id=header_user_id,
        display_name=decode_portal_header_value(header_user_name),
        role=header_role or "CONTRIBUTOR",
        owner_units=owner_units,
    )


def _actor_from_delegation(
    *,
    settings: PortalSettings,
    authorization: str | None,
    delegation_header: str,
) -> PortalActor:
    if not settings.delegation_secret:
        raise PortalAuthError("Delegation auth is not configured on knowledge portal.")
    if settings.require_service_token_with_delegation:
        expected = settings.service_token
        if expected:
            scheme, _, token = (authorization or "").partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
                raise PortalAuthError("Delegation requires a valid service bearer token.")
    try:
        from ai_ops_backoffice.knowledge_bridge.delegation import verify_delegation_envelope

        payload = verify_delegation_envelope(
            delegation_header,
            secret=settings.delegation_secret,
        )
    except Exception as exc:  # noqa: BLE001 - map all verify failures to auth error
        raise PortalAuthError(f"Invalid delegation envelope: {exc}") from exc

    role = str(payload.get("portalRole") or "CONTRIBUTOR")
    owner_units = [str(item) for item in (payload.get("ownerUnitIds") or []) if str(item)]
    return PortalActor(
        user_id=str(payload["sub"]),
        display_name=str(payload.get("name") or payload["sub"]),
        role=role,  # type: ignore[arg-type]
        owner_unit_ids=owner_units or list(settings.default_owner_unit_ids),
        tenant_id=str(payload.get("tenantId") or "") or None,
    )


async def search_via_agent_api(
    *,
    settings: PortalSettings,
    query: str,
    groups: list[str],
    limit: int = 4,
) -> list[dict[str, Any]]:
    if not settings.agent_api_url:
        return []
    headers = {"Content-Type": "application/json"}
    if settings.agent_api_token:
        headers["Authorization"] = f"Bearer {settings.agent_api_token}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{settings.agent_api_url.rstrip('/')}/retrieval/search",
            headers=headers,
            json={"query": query, "groups": groups, "limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("hits") or []


def draft_search_response(result: DraftSearchResult) -> dict[str, Any]:
    return {
        "hits": [
            {
                "chunkId": hit.chunk_id,
                "title": hit.title,
                "sourcePath": hit.source_path,
                "content": hit.content,
                "score": hit.score,
            }
            for hit in result.hits
        ],
        "matchedDraft": result.matched_draft,
        "leakedFromActiveRelease": result.leaked_from_active_release,
    }
