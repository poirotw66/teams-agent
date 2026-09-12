"""Source viewer and enterprise SSO routes for Teams Adapter.

Provides endpoints for viewing referenced RAG sources, authenticating via
Entra ID SSO with CSRF protection, and session cookie management (Spec A05-T1).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import threading
import time
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response

from .oidc import verify_entra_id_token
from .settings import AgentSettings
from .source_links import (
    create_viewer_token,
    resolve_source_file,
    source_media_type,
    verify_viewer_token,
)
from .source_viewer import render_source_document_html
from .viewer_sessions import get_viewer_membership_store

logger = logging.getLogger(__name__)

_consumed_sso_states: dict[str, float] = {}
_sso_lock = threading.Lock()


def _is_safe_redirect_target(url: str, allowed_base_url: str | None = None) -> bool:
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


def _mark_sso_state_consumed(state_id: str) -> bool:
    """Mark SSO state as consumed with one-time use semantics to prevent replay."""
    now_ts = time.time()
    with _sso_lock:
        expired = [k for k, ts in _consumed_sso_states.items() if now_ts - ts > 600]
        for k in expired:
            _consumed_sso_states.pop(k, None)
        if state_id in _consumed_sso_states:
            return False
        _consumed_sso_states[state_id] = now_ts
        return True


def _authenticated_viewer_subject(request: Request, settings: AgentSettings) -> str | None:
    """Extract and cryptographically verify login identity.

    External requests cannot spoof identity:
    - X-Viewer-Subject is trusted only if accompanied by a verified X-Gateway-Secret.
    - Bearer tokens are cryptographically verified using HMAC asset_signing_key or JWT signature.
    - Query parameter `token` / `viewer_token` is cryptographically verified via HMAC.
    - Session cookie `teams_viewer_token` is cryptographically verified via HMAC.
    - Unsigned / unverified tokens are rejected.
    """
    # 1. Gateway header forwarding (only trusted when gateway secret matches)
    for header in ("x-viewer-subject", "X-Viewer-Subject"):
        value = request.headers.get(header)
        if value and str(value).strip():
            gateway_secret = request.headers.get("x-gateway-secret") or request.headers.get("X-Gateway-Secret")
            expected_secret = settings.asset_signing_key or settings.api_token
            if (
                expected_secret
                and gateway_secret
                and hmac.compare_digest(gateway_secret.strip(), expected_secret.strip())
            ):
                return str(value).strip()

    # 2. Browser session cookie from authenticated login (/sources/login or SSO)
    cookie_token = request.cookies.get("teams_viewer_token") or request.cookies.get("viewer_token")
    if cookie_token and str(cookie_token).strip():
        payload = verify_viewer_token(str(cookie_token).strip(), settings)
        if payload and isinstance(payload.get("sub"), str) and payload["sub"].strip():
            query_tenant = request.query_params.get("tenantId")
            token_tenant = payload.get("tid")
            if not query_tenant or not token_tenant or str(query_tenant).strip() == str(token_tenant).strip():
                return payload["sub"].strip()

    # 3. Bearer token in Authorization header
    authorization = request.headers.get("authorization") or request.headers.get(
        "Authorization"
    )
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None

    raw_token = token.strip()

    # Try HMAC viewer token
    payload = verify_viewer_token(raw_token, settings)
    if payload and isinstance(payload.get("sub"), str) and payload["sub"].strip():
        return payload["sub"].strip()

    # Try JWT cryptographic signature verification
    verification_keys = [k for k in (settings.asset_signing_key, settings.client_secret) if k]
    if verification_keys:
        try:
            import jwt

            for key in verification_keys:
                try:
                    claims = jwt.decode(
                        raw_token,
                        key,
                        algorithms=["HS256", "HS384", "HS512"],
                        options={"verify_signature": True},
                    )
                    for claim_name in ("oid", "sub", "preferred_username", "upn", "email"):
                        val = claims.get(claim_name)
                        if isinstance(val, str) and val.strip():
                            return val.strip()
                except (jwt.PyJWTError, ValueError):
                    continue
        except ImportError:
            logger.debug("PyJWT not installed; skipping JWT token decoding")

    return None


def create_source_router(settings: AgentSettings) -> APIRouter:
    """Create router with RAG source document and SSO authentication endpoints."""
    router = APIRouter()

    @router.get("/rag-sources/{path:path}")
    async def source_document(path: str, request: Request) -> Response:
        auth_subject = _authenticated_viewer_subject(request, settings)
        try:
            resolved = resolve_source_file(
                path,
                request.query_params.get("expires"),
                request.query_params.get("signature"),
                settings,
                subject=request.query_params.get("subject"),
                groups=request.query_params.get("groups"),
                source_ref_id=request.query_params.get("sourceRefId"),
                tenant_id=request.query_params.get("tenantId"),
                authenticated_subject=auth_subject,
            )
            want_raw = request.query_params.get("raw", "").lower() in {
                "1",
                "true",
                "yes",
            }
            if (
                not want_raw
                and resolved.suffix.lower() in {".md", ".markdown", ".txt"}
            ):
                content = render_source_document_html(resolved, settings)
                content_type = "text/html; charset=utf-8"
            else:
                content = resolved.read_bytes()
                content_type = source_media_type(resolved)
        except PermissionError as error:
            accept = request.headers.get("accept", "").lower()
            if "text/html" in accept and not auth_subject:
                redirect_target = f"/sources/login?redirect_url={quote(str(request.url))}"
                return Response(
                    status_code=302,
                    headers={"Location": redirect_target},
                )
            raise HTTPException(status_code=403, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Not Found") from error

        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Cache-Control": f"private, max-age={settings.asset_url_ttl_seconds}",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": (
                    "inline; filename*=UTF-8''"
                    + quote(resolved.name)
                ),
            },
        )

    @router.get("/sources/login")
    async def viewer_login_page(request: Request) -> Response:
        redirect_url = request.query_params.get("redirect_url") or request.query_params.get("redirect") or ""
        auth_subject = _authenticated_viewer_subject(request, settings)
        if auth_subject:
            target = redirect_url if _is_safe_redirect_target(redirect_url, settings.public_base_url) else "/healthz"
            return Response(status_code=302, headers={"Location": target})

        token = request.query_params.get("token") or request.query_params.get("viewer_token")
        if token and str(token).strip():
            payload = verify_viewer_token(str(token).strip(), settings)
            if payload and payload.get("sub"):
                target = redirect_url if _is_safe_redirect_target(redirect_url, settings.public_base_url) else "/healthz"
                resp = Response(status_code=302, headers={"Location": target})
                resp.set_cookie(
                    "teams_viewer_token",
                    str(token).strip(),
                    max_age=settings.asset_url_ttl_seconds,
                    httponly=True,
                    samesite="lax",
                )
                return resp

        # Traditional Chinese viewer login / SSO landing page
        escaped_redirect = html.escape(redirect_url)
        page = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>知識庫來源存取驗證</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f5f5f5;
      margin: 0;
      padding: 48px 16px;
      display: flex;
      justify-content: center;
    }}
    .card {{
      max-width: 480px;
      width: 100%;
      background: #ffffff;
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.06);
      padding: 32px;
      box-sizing: border-box;
    }}
    h2 {{
      margin-top: 0;
      color: #242424;
      font-size: 20px;
    }}
    p {{
      color: #616161;
      line-height: 1.6;
      font-size: 14px;
    }}
    .callout {{
      background: #f0f4ff;
      border-left: 4px solid #5b5fc7;
      padding: 12px 16px;
      border-radius: 4px;
      font-size: 13px;
      color: #242424;
      margin: 20px 0;
      line-height: 1.5;
    }}
    .sso-btn {{
      display: block;
      width: 100%;
      box-sizing: border-box;
      text-align: center;
      text-decoration: none;
      background: #0078d4;
      color: #ffffff;
      border-radius: 4px;
      padding: 12px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease;
      margin-bottom: 20px;
    }}
    .sso-btn:hover {{
      background: #106ebe;
    }}
    .divider {{
      display: flex;
      align-items: center;
      text-align: center;
      margin: 20px 0;
      color: #8a8886;
      font-size: 12px;
    }}
    .divider::before, .divider::after {{
      content: "";
      flex: 1;
      border-bottom: 1px solid #e0e0e0;
    }}
    .divider:not(:empty)::before {{
      margin-right: .75em;
    }}
    .divider:not(:empty)::after {{
      margin-left: .75em;
    }}
    label {{
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #242424;
      margin-bottom: 8px;
    }}
    input[type=text] {{
      width: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
      border: 1px solid #c8c8c8;
      border-radius: 4px;
      font-size: 14px;
      margin-bottom: 20px;
    }}
    input[type=text]:focus {{
      outline: none;
      border-color: #5b5fc7;
      box-shadow: 0 0 0 2px rgba(91,95,199,0.2);
    }}
    button {{
      width: 100%;
      background: #5b5fc7;
      color: #ffffff;
      border: none;
      border-radius: 4px;
      padding: 12px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease;
    }}
    button:hover {{
      background: #4f52b2;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h2>知識庫來源文件存取驗證</h2>
    <p>為了維護企業資訊安全，存取引用來源文件需透過企業單一登入 (SSO) 或經由授權閘道完成身分確認。</p>
    <div class="callout">
      <strong>存取說明</strong><br />
      引用來源文件受企業授權與存取控制保護。請使用您的 Microsoft 365 / 公司帳號完成登入，或使用經授權核發的檢視憑證。
    </div>
    <a href="/sources/auth/login?redirect_url={escaped_redirect}" class="sso-btn">使用 Microsoft 365 / 公司帳號登入 (SSO)</a>
    <div class="divider">或使用檢視憑證驗證</div>
    <form method="POST" action="/sources/login">
      <input type="hidden" name="redirect_url" value="{escaped_redirect}" />
      <label for="token">檢視憑證 (Viewer Token)：</label>
      <input type="text" id="token" name="token" placeholder="請輸入或貼上有效的 Viewer Token" required />
      <button type="submit">驗證身分並開啟文件</button>
    </form>
  </div>
</body>
</html>"""
        return Response(content=page.encode("utf-8"), media_type="text/html; charset=utf-8")

    @router.get("/sources/auth/login")
    async def viewer_auth_login(request: Request) -> Response:
        redirect_url = request.query_params.get("redirect_url") or request.query_params.get("redirect") or ""
        auth_subject = _authenticated_viewer_subject(request, settings)
        if auth_subject:
            target = redirect_url if _is_safe_redirect_target(redirect_url, settings.public_base_url) else "/healthz"
            return Response(status_code=302, headers={"Location": target})

        tenant_id = settings.tenant_id or "common"
        client_id = settings.client_id
        if not client_id:
            return Response(
                status_code=302,
                headers={"Location": f"/sources/login?redirect_url={quote(redirect_url)}&error=sso_unconfigured"},
            )

        base_url = settings.public_base_url or str(request.base_url).rstrip("/")
        callback_url = f"{base_url}/sources/auth/callback"

        state_id = uuid.uuid4().hex
        nonce = uuid.uuid4().hex
        state_payload = {
            "state_id": state_id,
            "redirect_url": redirect_url,
            "ts": time.time(),
        }
        secret = settings.asset_signing_key or settings.api_token or "viewer-state-secret"
        state_bytes = json.dumps(state_payload, sort_keys=True).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), state_bytes, hashlib.sha256).hexdigest()
        state_param = f"{base64.urlsafe_b64encode(state_bytes).decode('ascii')}.{sig}"

        session_payload = {
            "state_id": state_id,
            "nonce": nonce,
            "ts": time.time(),
        }
        session_bytes = json.dumps(session_payload, sort_keys=True).encode("utf-8")
        session_sig = hmac.new(secret.encode("utf-8"), session_bytes, hashlib.sha256).hexdigest()
        session_cookie_val = f"{base64.urlsafe_b64encode(session_bytes).decode('ascii')}.{session_sig}"

        auth_url = (
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
            f"?client_id={quote(client_id)}"
            f"&response_type=code"
            f"&redirect_uri={quote(callback_url)}"
            f"&response_mode=query"
            f"&scope=openid%20profile%20email"
            f"&state={quote(state_param)}"
            f"&nonce={quote(nonce)}"
        )
        resp = Response(status_code=302, headers={"Location": auth_url})
        resp.set_cookie(
            "sso_auth_session",
            session_cookie_val,
            max_age=600,
            httponly=True,
            samesite="lax",
        )
        return resp

    @router.get("/sources/auth/callback")
    async def viewer_auth_callback(request: Request) -> Response:
        code = request.query_params.get("code")
        state_param = request.query_params.get("state") or ""
        if not code or not state_param:
            raise HTTPException(status_code=400, detail="Missing authorization code or state.")

        secret = settings.asset_signing_key or settings.api_token or "viewer-state-secret"
        raw_state, _, sig = state_param.partition(".")
        try:
            state_bytes = base64.urlsafe_b64decode(raw_state.encode("ascii"))
            expected_sig = hmac.new(secret.encode("utf-8"), state_bytes, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                raise HTTPException(status_code=403, detail="Invalid state signature.")
            state_data = json.loads(state_bytes.decode("utf-8"))
            if time.time() - float(state_data.get("ts", 0)) > 600:
                raise HTTPException(status_code=403, detail="State has expired.")
        except Exception as err:
            raise HTTPException(status_code=403, detail="Invalid or expired SSO state.") from err

        state_id = str(state_data.get("state_id") or "")

        # Verify browser session cookie binding
        raw_session_cookie = request.cookies.get("sso_auth_session")
        if not raw_session_cookie or "." not in raw_session_cookie:
            raise HTTPException(status_code=403, detail="Missing or invalid SSO session cookie (CSRF protection).")

        raw_sess, _, sess_sig = raw_session_cookie.partition(".")
        try:
            sess_bytes = base64.urlsafe_b64decode(raw_sess.encode("ascii"))
            expected_sess_sig = hmac.new(secret.encode("utf-8"), sess_bytes, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sess_sig, expected_sess_sig):
                raise HTTPException(status_code=403, detail="Invalid SSO session signature.")
            session_data = json.loads(sess_bytes.decode("utf-8"))
        except Exception as err:
            raise HTTPException(status_code=403, detail="Corrupted SSO session cookie.") from err

        if not state_id or session_data.get("state_id") != state_id:
            raise HTTPException(status_code=403, detail="SSO state does not match login session.")

        # One-time state consumption check
        if not _mark_sso_state_consumed(state_id):
            raise HTTPException(status_code=403, detail="SSO state has already been consumed.")

        expected_nonce = str(session_data.get("nonce") or "")

        raw_redirect_url = str(state_data.get("redirect_url") or "")
        target = raw_redirect_url if _is_safe_redirect_target(raw_redirect_url, settings.public_base_url) else "/healthz"

        base_url = settings.public_base_url or str(request.base_url).rstrip("/")
        callback_url = f"{base_url}/sources/auth/callback"
        tenant_id = settings.tenant_id or "common"
        client_id = settings.client_id
        client_secret = settings.client_secret

        subject: str | None = None
        groups: list[str] = []

        token_exchanger = getattr(request.app.state, "oauth_token_exchanger", None)
        if token_exchanger is not None:
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
                subject = (
                    claims.get("oid")
                    or claims.get("sub")
                    or claims.get("preferred_username")
                    or claims.get("email")
                )
                groups = list(claims.get("groups") or [])
                tid = claims.get("tid")
                if tid:
                    tenant_id = tid
            else:
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

                subject = (
                    token_data.get("oid")
                    or token_data.get("sub")
                    or token_data.get("preferred_username")
                    or token_data.get("email")
                )
                groups = list(token_data.get("groups") or [])
                if token_data.get("tenant_id"):
                    tenant_id = token_data["tenant_id"]
        elif client_id and client_secret:
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
                subject = (
                    claims.get("oid")
                    or claims.get("sub")
                    or claims.get("preferred_username")
                    or claims.get("email")
                )
                groups = list(claims.get("groups") or [])
                tid = claims.get("tid")
                if tid:
                    tenant_id = tid

        if not subject:
            raise HTTPException(status_code=401, detail="Failed to resolve authenticated subject from SSO.")

        store = get_viewer_membership_store(settings)
        existing_membership = store.resolve(subject)
        if not groups and existing_membership and existing_membership.groups:
            groups = list(existing_membership.groups)

        store.remember(subject, groups=groups, tenant_id=tenant_id)

        viewer_token = create_viewer_token(
            subject,
            settings,
            tenant_id=tenant_id,
        )
        resp = Response(status_code=302, headers={"Location": target})
        resp.set_cookie(
            "teams_viewer_token",
            viewer_token,
            max_age=settings.asset_url_ttl_seconds,
            httponly=True,
            samesite="lax",
        )
        resp.delete_cookie("sso_auth_session")
        return resp

    @router.post("/sources/login")
    async def viewer_login_submit(request: Request) -> Response:
        form_data: dict[str, Any] = {}
        raw_body = await request.body()
        if raw_body:
            content_type = request.headers.get("content-type", "").lower()
            if "application/json" in content_type:
                try:
                    form_data = json.loads(raw_body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    form_data = {}
            else:
                from urllib.parse import parse_qs

                try:
                    parsed_qs = parse_qs(raw_body.decode("utf-8"))
                    form_data = {k: v[0] for k, v in parsed_qs.items()}
                except (ValueError, UnicodeDecodeError):
                    form_data = {}
        token = str(form_data.get("token") or "").strip()
        redirect_url = str(form_data.get("redirect_url") or "").strip()
        payload = verify_viewer_token(token, settings)
        if not payload or not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid or expired viewer token.")

        target = redirect_url if _is_safe_redirect_target(redirect_url, settings.public_base_url) else "/healthz"
        resp = Response(status_code=302, headers={"Location": target})
        resp.set_cookie(
            "teams_viewer_token",
            token,
            max_age=settings.asset_url_ttl_seconds,
            httponly=True,
            samesite="lax",
        )
        return resp

    @router.post("/sources/logout")
    async def viewer_logout() -> Response:
        resp = Response(content=b'{"status":"ok"}', media_type="application/json")
        resp.delete_cookie("teams_viewer_token")
        return resp

    return router
