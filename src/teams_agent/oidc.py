"""Microsoft Entra ID OIDC token verification module.

Provides cryptographic verification of Entra ID JWT tokens against
Microsoft OpenID Connect discovery keys, strictly enforcing tenant isolation,
issuer validation, audience, expiration, and nonce checking (Spec A05-T1).
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Any

from fastapi import HTTPException

from .oidc_tenant import validate_token_tenant_and_issuer

logger = logging.getLogger(__name__)


def _resolve_signing_key(
    id_token: str,
    *,
    tenant_id: str,
    jwks_client: Any,
    signing_key: Any,
) -> Any:
    import jwt

    if signing_key is not None:
        return signing_key
    if jwks_client is not None:
        try:
            return jwks_client.get_signing_key_from_jwt(id_token).key
        except Exception as err:
            raise HTTPException(
                status_code=401, detail=f"Failed to fetch JWKS signing key: {err}"
            ) from err
    jwks_url = (
        f"https://login.microsoftonline.com/{tenant_id or 'common'}/discovery/v2.0/keys"
    )
    try:
        client = jwt.PyJWKClient(jwks_url)
        return client.get_signing_key_from_jwt(id_token).key
    except Exception as err:
        raise HTTPException(
            status_code=401, detail=f"Failed to resolve OIDC signing key: {err}"
        ) from err


def _decode_id_token_claims(
    id_token: str,
    *,
    key: Any,
    client_id: str,
    algorithms: list[str],
) -> dict[str, Any]:
    import jwt

    try:
        return jwt.decode(
            id_token,
            key,
            algorithms=algorithms,
            audience=client_id,
            options={
                "verify_signature": True,
                "verify_aud": True,
                "verify_exp": True,
                "require": ["exp", "iss", "aud", "nonce"],
            },
        )
    except jwt.ExpiredSignatureError as err:
        raise HTTPException(status_code=401, detail="ID token has expired.") from err
    except jwt.InvalidAudienceError as err:
        raise HTTPException(
            status_code=401, detail="ID token audience mismatch."
        ) from err
    except jwt.MissingRequiredClaimError as err:
        raise HTTPException(
            status_code=401, detail=f"ID token missing required claim: {err}"
        ) from err
    except jwt.PyJWTError as err:
        raise HTTPException(
            status_code=401,
            detail=f"ID token signature verification failed: {err}",
        ) from err


def verify_entra_id_token(
    id_token: str,
    *,
    client_id: str,
    tenant_id: str,
    expected_nonce: str,
    allowed_tenants: Collection[str] | None = None,
    jwks_client: Any = None,
    signing_key: Any = None,
    allowed_algorithms: list[str] | None = None,
) -> dict[str, Any]:
    """Cryptographically verify Microsoft Entra ID token according to OIDC standards.

    Strictly enforces tenant boundaries:
    - If single-tenant (configured with a specific tenant GUID/name):
      the issuer MUST be from that configured tenant, and token `tid` (if present)
      must match `tenant_id`. Unverified token claims NEVER widen allowed issuers.
    - If `allowed_tenants` is specified:
      the token's tenant MUST be in `allowed_tenants`, and issuer MUST match.
    - If multi-tenant ('common', 'organizations', 'consumers') without explicit list:
      the token's tenant must be non-empty, and issuer must match that tenant.
    """
    if not id_token or not isinstance(id_token, str):
        raise HTTPException(status_code=401, detail="Missing or invalid ID token.")

    algorithms = allowed_algorithms or ["RS256"]
    key = _resolve_signing_key(
        id_token,
        tenant_id=tenant_id,
        jwks_client=jwks_client,
        signing_key=signing_key,
    )
    claims = _decode_id_token_claims(
        id_token, key=key, client_id=client_id, algorithms=algorithms
    )

    validate_token_tenant_and_issuer(
        token_iss=str(claims.get("iss") or "").strip(),
        token_tid=str(claims.get("tid") or "").strip(),
        tenant_id=tenant_id,
        allowed_tenants=allowed_tenants,
    )

    token_nonce = str(claims.get("nonce") or "").strip()
    if not token_nonce or token_nonce != expected_nonce:
        raise HTTPException(status_code=401, detail="ID token nonce mismatch.")

    return claims
