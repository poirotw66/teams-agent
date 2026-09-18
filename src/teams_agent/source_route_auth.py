"""Viewer authentication and SSO state helpers for source routes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from typing import Any

from fastapi import HTTPException, Request

from .oidc import verify_entra_id_token
from .settings import AgentSettings
from .source_links import verify_viewer_token
from .viewer_sessions import get_viewer_membership_store

logger = logging.getLogger(__name__)

_consumed_sso_states: dict[str, float] = {}
_sso_lock = threading.Lock()


def is_safe_redirect_target(url: str, allowed_base_url: str | None = None) -> bool:
    """Validate that redirect target is safe against open redirect attacks."""
    if not url:
        return False
    # Prohibit protocol-relative and backslash URLs that evade browser domain boundaries
    if url.startswith(("//", "/\\", "\\\\", "\\/")):
        return False
    # Allow safe relative paths
    if url.startswith("/") and not url.startswith(("//", "/\\")):
        return True
    if allowed_base_url:
        from urllib.parse import urlparse

        try:
            target = urlparse(url)
            base = urlparse(allowed_base_url)
            return (
                target.scheme in ("http", "https")
                and target.scheme == base.scheme
                and target.netloc == base.netloc
            )
        except ValueError:
            return False
    return False


def mark_sso_state_consumed(state_id: str) -> bool:
    """Mark SSO state as consumed with one-time use semantics to prevent replay."""
    now_ts = time.time()
    with _sso_lock:
        expired = [k for k, ts in _consumed_sso_states.items() if now_ts - ts > 600]
        for key in expired:
            _consumed_sso_states.pop(key, None)
        if state_id in _consumed_sso_states:
            return False
        _consumed_sso_states[state_id] = now_ts
        return True


def is_gateway_authenticated(request: Request, settings: AgentSettings) -> bool:
    """True when Playground/gateway shared secret matches (trusted subject header)."""
    gateway_secret = request.headers.get("x-gateway-secret") or request.headers.get(
        "X-Gateway-Secret"
    )
    expected_secret = settings.asset_signing_key or settings.api_token
    return bool(
        expected_secret
        and gateway_secret
        and hmac.compare_digest(gateway_secret.strip(), expected_secret.strip())
    )


def seed_gateway_membership(
    request: Request,
    settings: AgentSettings,
    *,
    subject: str | None,
) -> None:
    """Seed the lab gateway's public membership when no chat turn exists."""
    if not subject or not is_gateway_authenticated(request, settings):
        return
    store = get_viewer_membership_store(settings)
    if store.resolve(subject) is not None:
        return
    store.remember(
        subject,
        groups=("grp_public",),
        tenant_id=request.query_params.get("tenantId") or "default",
        revoked=False,
        ttl_seconds=float(settings.asset_url_ttl_seconds),
    )


def authenticated_viewer_subject(request: Request, settings: AgentSettings) -> str | None:
    """Extract and cryptographically verify login identity.

    External requests cannot spoof identity:
    - X-Viewer-Subject is trusted only if accompanied by a verified X-Gateway-Secret.
    - Bearer tokens are cryptographically verified using HMAC asset_signing_key or JWT signature.
    - Query parameter `token` / `viewer_token` is cryptographically verified via HMAC.
    - Session cookie `teams_viewer_token` is cryptographically verified via HMAC.
    - Unsigned / unverified tokens are rejected.
    """
    for header in ("x-viewer-subject", "X-Viewer-Subject"):
        value = request.headers.get(header)
        if value and str(value).strip() and is_gateway_authenticated(request, settings):
            return str(value).strip()

    cookie_token = request.cookies.get("teams_viewer_token") or request.cookies.get("viewer_token")
    if cookie_token and str(cookie_token).strip():
        subject = _subject_from_viewer_token(
            str(cookie_token).strip(),
            settings,
            query_tenant=request.query_params.get("tenantId"),
        )
        if subject:
            return subject

    authorization = request.headers.get("authorization") or request.headers.get("Authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return _subject_from_bearer_token(token.strip(), settings)


def _subject_from_viewer_token(
    raw_token: str,
    settings: AgentSettings,
    *,
    query_tenant: str | None = None,
) -> str | None:
    payload = verify_viewer_token(raw_token, settings)
    if not payload or not isinstance(payload.get("sub"), str) or not payload["sub"].strip():
        return None
    token_tenant = payload.get("tid")
    if query_tenant and token_tenant and str(query_tenant).strip() != str(token_tenant).strip():
        return None
    return payload["sub"].strip()


def _subject_from_bearer_token(raw_token: str, settings: AgentSettings) -> str | None:
    subject = _subject_from_viewer_token(raw_token, settings)
    if subject:
        return subject

    verification_keys = [key for key in (settings.asset_signing_key, settings.client_secret) if key]
    if not verification_keys:
        return None
    try:
        import jwt
    except ImportError:
        logger.debug("PyJWT not installed; skipping JWT token decoding")
        return None

    for key in verification_keys:
        try:
            claims = jwt.decode(
                raw_token,
                key,
                algorithms=["HS256", "HS384", "HS512"],
                options={"verify_signature": True},
            )
        except (jwt.PyJWTError, ValueError):
            continue
        for claim_name in ("oid", "sub", "preferred_username", "upn", "email"):
            value = claims.get(claim_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def sso_signing_secret(settings: AgentSettings) -> str:
    return settings.asset_signing_key or settings.api_token or "viewer-state-secret"


def encode_signed_blob(payload: dict[str, Any], secret: str) -> str:
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"{base64.urlsafe_b64encode(payload_bytes).decode('ascii')}.{signature}"


def decode_signed_blob(raw_value: str, secret: str) -> dict[str, Any]:
    raw_payload, _, signature = raw_value.partition(".")
    payload_bytes = base64.urlsafe_b64decode(raw_payload.encode("ascii"))
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid signature")
    data = json.loads(payload_bytes.decode("utf-8"))
    if not isinstance(data, dict):
        raise TypeError("Signed blob payload must be an object")
    return data


def parse_sso_callback_state(state_param: str, secret: str) -> dict[str, Any]:
    try:
        state_data = decode_signed_blob(state_param, secret)
    except ValueError as err:
        if str(err) == "Invalid signature":
            raise HTTPException(status_code=403, detail="Invalid state signature.") from err
        raise HTTPException(status_code=403, detail="Invalid or expired SSO state.") from err
    except Exception as err:
        raise HTTPException(status_code=403, detail="Invalid or expired SSO state.") from err
    if time.time() - float(state_data.get("ts", 0)) > 600:
        raise HTTPException(status_code=403, detail="State has expired.")
    return state_data


def parse_sso_session_cookie(raw_session_cookie: str | None, secret: str) -> dict[str, Any]:
    if not raw_session_cookie or "." not in raw_session_cookie:
        raise HTTPException(
            status_code=403, detail="Missing or invalid SSO session cookie (CSRF protection)."
        )
    try:
        return decode_signed_blob(raw_session_cookie, secret)
    except ValueError as err:
        if str(err) == "Invalid signature":
            raise HTTPException(status_code=403, detail="Invalid SSO session signature.") from err
        raise HTTPException(status_code=403, detail="Corrupted SSO session cookie.") from err
    except Exception as err:
        raise HTTPException(status_code=403, detail="Corrupted SSO session cookie.") from err


def subject_from_identity_claims(claims: dict[str, Any]) -> str | None:
    subject = (
        claims.get("oid")
        or claims.get("sub")
        or claims.get("preferred_username")
        or claims.get("email")
    )
    if subject is None:
        return None
    text = str(subject).strip()
    return text or None


def _validate_exchanger_token_claims(
    token_data: dict[str, Any],
    *,
    client_id: str | None,
    tenant_id: str,
    expected_nonce: str,
) -> None:
    now_ts = time.time()
    exp = token_data.get("exp")
    if exp is not None and float(exp) < now_ts - 60:
        raise HTTPException(status_code=401, detail="ID token has expired.")
    aud = token_data.get("aud")
    if aud and aud != client_id:
        raise HTTPException(status_code=401, detail="ID token audience mismatch.")
    token_nonce = token_data.get("nonce")
    if expected_nonce and token_nonce and token_nonce != expected_nonce:
        raise HTTPException(status_code=401, detail="ID token nonce mismatch.")
    token_tid = token_data.get("tenant_id") or token_data.get("tid")
    if (
        tenant_id
        and tenant_id not in ("common", "organizations", "consumers")
        and token_tid
        and token_tid != tenant_id
    ):
        raise HTTPException(status_code=401, detail="ID token tenant mismatch.")


async def resolve_sso_identity(
    request: Request,
    settings: AgentSettings,
    *,
    code: str,
    callback_url: str,
    expected_nonce: str,
    tenant_id: str,
) -> tuple[str, list[str], str]:
    """Exchange an SSO authorization code for subject, groups, and tenant."""
    client_id = settings.client_id
    client_secret = settings.client_secret
    subject: str | None = None
    groups: list[str] = []
    resolved_tenant = tenant_id

    token_exchanger = getattr(request.app.state, "oauth_token_exchanger", None)
    if token_exchanger is not None:
        subject, groups, resolved_tenant = await _identity_from_token_exchanger(
            request,
            token_exchanger,
            code=code,
            callback_url=callback_url,
            client_id=client_id,
            tenant_id=resolved_tenant,
            expected_nonce=expected_nonce,
        )
    elif client_id and client_secret:
        subject, groups, resolved_tenant = await _identity_from_token_endpoint(
            request,
            code=code,
            callback_url=callback_url,
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=resolved_tenant,
            expected_nonce=expected_nonce,
        )

    if not subject:
        raise HTTPException(
            status_code=401, detail="Failed to resolve authenticated subject from SSO."
        )
    return subject, groups, resolved_tenant


async def _identity_from_token_exchanger(
    request: Request,
    token_exchanger: Any,
    *,
    code: str,
    callback_url: str,
    client_id: str | None,
    tenant_id: str,
    expected_nonce: str,
) -> tuple[str | None, list[str], str]:
    token_data = await token_exchanger(code, callback_url)
    if "id_token" in token_data and isinstance(token_data["id_token"], str):
        claims = verify_entra_id_token(
            token_data["id_token"],
            client_id=client_id,
            tenant_id=tenant_id,
            expected_nonce=expected_nonce,
            jwks_client=getattr(request.app.state, "jwks_client", None),
            signing_key=getattr(request.app.state, "id_token_key", None),
            allowed_algorithms=getattr(request.app.state, "id_token_algorithms", None),
        )
        resolved_tenant = str(claims.get("tid") or tenant_id)
        return (
            subject_from_identity_claims(claims),
            list(claims.get("groups") or []),
            resolved_tenant,
        )

    _validate_exchanger_token_claims(
        token_data,
        client_id=client_id,
        tenant_id=tenant_id,
        expected_nonce=expected_nonce,
    )
    resolved_tenant = str(token_data.get("tenant_id") or tenant_id)
    return (
        subject_from_identity_claims(token_data),
        list(token_data.get("groups") or []),
        resolved_tenant,
    )


async def _identity_from_token_endpoint(
    request: Request,
    *,
    code: str,
    callback_url: str,
    client_id: str,
    client_secret: str,
    tenant_id: str,
    expected_nonce: str,
) -> tuple[str | None, list[str], str]:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        token_resp = await http_client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback_url,
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Token endpoint returned non-200.")
        token_json = token_resp.json()
        id_token = token_json.get("id_token")
        if not id_token:
            raise HTTPException(status_code=401, detail="Missing id_token in token response.")

        claims = verify_entra_id_token(
            id_token,
            client_id=client_id,
            tenant_id=tenant_id,
            expected_nonce=expected_nonce,
            jwks_client=getattr(request.app.state, "jwks_client", None),
            signing_key=getattr(request.app.state, "id_token_key", None),
            allowed_algorithms=getattr(request.app.state, "id_token_algorithms", None),
        )
        resolved_tenant = str(claims.get("tid") or tenant_id)
        return (
            subject_from_identity_claims(claims),
            list(claims.get("groups") or []),
            resolved_tenant,
        )
