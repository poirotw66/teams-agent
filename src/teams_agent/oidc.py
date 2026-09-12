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

logger = logging.getLogger(__name__)


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
    import jwt

    if not id_token or not isinstance(id_token, str):
        raise HTTPException(status_code=401, detail="Missing or invalid ID token.")

    algorithms = allowed_algorithms or ["RS256"]
    key = signing_key
    if key is None:
        if jwks_client is not None:
            try:
                key = jwks_client.get_signing_key_from_jwt(id_token).key
            except Exception as err:
                raise HTTPException(status_code=401, detail=f"Failed to fetch JWKS signing key: {err}") from err
        else:
            jwks_url = f"https://login.microsoftonline.com/{tenant_id or 'common'}/discovery/v2.0/keys"
            try:
                client = jwt.PyJWKClient(jwks_url)
                key = client.get_signing_key_from_jwt(id_token).key
            except Exception as err:
                raise HTTPException(status_code=401, detail=f"Failed to resolve OIDC signing key: {err}") from err

    try:
        claims = jwt.decode(
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
        raise HTTPException(status_code=401, detail="ID token audience mismatch.") from err
    except jwt.MissingRequiredClaimError as err:
        raise HTTPException(status_code=401, detail=f"ID token missing required claim: {err}") from err
    except jwt.PyJWTError as err:
        raise HTTPException(status_code=401, detail=f"ID token signature verification failed: {err}") from err

    token_iss = str(claims.get("iss") or "").strip()
    token_tid = str(claims.get("tid") or "").strip()
    is_single_tenant = bool(tenant_id and tenant_id not in ("common", "organizations", "consumers"))

    if is_single_tenant:
        # Single-tenant: only the configured tenant's endpoints are accepted
        allowed_issuers = {
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://sts.windows.net/{tenant_id}/",
        }
        if token_iss not in allowed_issuers:
            raise HTTPException(status_code=401, detail=f"ID token issuer mismatch: {token_iss}")
        if token_tid and token_tid != tenant_id:
            raise HTTPException(
                status_code=401,
                detail=f"ID token tenant mismatch: expected {tenant_id}, got {token_tid}.",
            )
    elif allowed_tenants is not None:
        allowed_set = {str(t).strip() for t in allowed_tenants if str(t).strip()}
        if token_tid and token_tid not in allowed_set:
            raise HTTPException(
                status_code=401,
                detail=f"ID token tenant {token_tid} is not in allowed tenants.",
            )
        allowed_issuers = {
            f"https://login.microsoftonline.com/{t}/v2.0" for t in allowed_set
        } | {
            f"https://sts.windows.net/{t}/" for t in allowed_set
        }
        if token_iss not in allowed_issuers:
            raise HTTPException(status_code=401, detail=f"ID token issuer mismatch: {token_iss}")
    else:
        # Multi-tenant without allowlist: must still have non-empty tid
        if not token_tid:
            raise HTTPException(status_code=401, detail="ID token missing tid claim.")
        allowed_issuers = {
            f"https://login.microsoftonline.com/{token_tid}/v2.0",
            f"https://sts.windows.net/{token_tid}/",
        }
        if token_iss not in allowed_issuers:
            raise HTTPException(status_code=401, detail=f"ID token issuer mismatch: {token_iss}")

    token_nonce = str(claims.get("nonce") or "").strip()
    if not token_nonce or token_nonce != expected_nonce:
        raise HTTPException(status_code=401, detail="ID token nonce mismatch.")

    return claims
