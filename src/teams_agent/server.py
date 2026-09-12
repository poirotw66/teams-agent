"""HTTP surface for the Teams Adapter.

The Microsoft Teams SDK owns `POST /api/messages`: `App.initialize()`
registers that route on whatever `HttpServerAdapter` it is given and guards
it with Bot Framework JWT validation. Everything else the adapter exposes
(`/healthz`, `/readyz`, and the signed `/rag-assets/` image endpoint) is
registered here on the same FastAPI instance, so a single uvicorn server
serves both.

These extra routes are deliberately unauthenticated:

- `/healthz` and `/readyz` are Cloud Run probes and return no user data.
- `/rag-assets/{path}` is guarded by its own HMAC signature + expiry
  (`teams_agent.media`), because Teams itself fetches those image URLs
  without any bearer token.
"""

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

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from microsoft_teams.apps import FastAPIAdapter
from microsoft_teams.apps.auth import TokenValidator

from .media import render_teams_image, resolve_asset
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


class EntraPlaygroundTokenValidator:
    """Validate the Playground's Entra token without a Bot Framework claim.

    Entra client-credentials tokens do not contain Bot Framework's
    ``serviceurl`` claim. Signature, issuer, audience and expiry are still
    validated by the SDK's Entra validator.
    """

    def __init__(self, validator: TokenValidator) -> None:
        self._validator = validator

    async def validate_token(
        self,
        raw_token: str,
        service_url: str | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        del service_url
        return await self._validator.validate_token(raw_token, None, scope)


class DualInboundTokenValidator:
    """Accept either Bot Framework (Teams) or Entra (Playground) JWTs.

    Real Teams / Azure Bot traffic uses the Bot Framework issuer. The hosted
    Agents Playground uses a tenant-scoped Entra client-credentials token.
    One Cloud Run adapter must accept both when demos and private Apps share
    the same messaging endpoint.
    """

    def __init__(self, primary: Any, secondary: Any) -> None:
        self._primary = primary
        self._secondary = secondary

    async def validate_token(
        self,
        raw_token: str,
        service_url: str | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._primary.validate_token(raw_token, service_url, scope)
        except Exception as primary_error:  # noqa: BLE001 - try alternate issuer
            try:
                return await self._secondary.validate_token(
                    raw_token, service_url, scope
                )
            except Exception:  # noqa: BLE001 - preserve primary issuer failure
                raise primary_error from None


def _entra_playground_validator(settings: AgentSettings) -> EntraPlaygroundTokenValidator:
    if not settings.client_id or not settings.tenant_id:
        raise ValueError("Entra inbound auth requires client_id and tenant_id")
    return EntraPlaygroundTokenValidator(
        TokenValidator.for_entra(
            settings.client_id,
            settings.tenant_id,
        )
    )


def configure_inbound_auth(app: object, settings: AgentSettings) -> None:
    """Select the JWT issuer used for inbound Playground/Teams activities."""
    mode = settings.teams_inbound_auth_mode
    if mode == "botframework":
        return

    # The SDK currently exposes no public hook for replacing only the inbound
    # validator. This preserves Bot Framework credentials for outbound sends
    # while accepting the Playground's tenant-scoped Entra token.
    server = app.server  # type: ignore[attr-defined]
    entra = _entra_playground_validator(settings)
    if mode == "entra":
        server._token_validator = entra
        logger.info("Inbound activity JWT validation configured for Entra Playground")
        return

    # mode == "both": keep the SDK Bot Framework validator and fall back to Entra.
    server._token_validator = DualInboundTokenValidator(
        server._token_validator,
        entra,
    )
    logger.info(
        "Inbound activity JWT validation configured for Bot Framework and Entra Playground"
    )

def build_readiness(settings: AgentSettings) -> dict[str, object]:
    """Readiness payload reported by `GET /readyz`.

    `teamsAuth` reports whether the Teams SDK has app credentials to validate
    inbound Bot Framework JWTs with -- the Teams SDK equivalent of the old
    Azure Bot service-connection check.
    """
    return {
        "status": "ready" if settings.ready and settings.teams_auth_ready else "not_ready",
        "agentMode": settings.mode,
        "teamsAuth": "ready" if settings.teams_auth_ready else "not_configured",
        "ragImages": "ready" if settings.images_ready else "disabled",
    }


_consumed_sso_states: dict[str, float] = {}
_sso_lock = threading.Lock()


def _is_safe_redirect_target(url: str, allowed_base_url: str | None = None) -> bool:
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
    now_ts = time.time()
    with _sso_lock:
        expired = [k for k, ts in _consumed_sso_states.items() if now_ts - ts > 600]
        for k in expired:
            _consumed_sso_states.pop(k, None)
        if state_id in _consumed_sso_states:
            return False
        _consumed_sso_states[state_id] = now_ts
        return True


def verify_entra_id_token(
    id_token: str,
    *,
    client_id: str,
    tenant_id: str,
    expected_nonce: str,
    jwks_client: Any = None,
    signing_key: Any = None,
    allowed_algorithms: list[str] | None = None,
) -> dict[str, Any]:
    """Cryptographically verify Microsoft Entra ID token according to OIDC standards."""
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

    # Validate Issuer (iss)
    token_iss = str(claims.get("iss") or "").strip()
    token_tid = str(claims.get("tid") or tenant_id or "").strip()
    allowed_issuers = {
        f"https://login.microsoftonline.com/{token_tid}/v2.0",
        f"https://sts.windows.net/{token_tid}/",
    }
    if tenant_id and tenant_id not in ("common", "organizations", "consumers"):
        allowed_issuers.add(f"https://login.microsoftonline.com/{tenant_id}/v2.0")
        allowed_issuers.add(f"https://sts.windows.net/{tenant_id}/")

    if token_iss not in allowed_issuers:
        raise HTTPException(status_code=401, detail=f"ID token issuer mismatch: {token_iss}")

    # Validate Nonce (nonce)
    token_nonce = str(claims.get("nonce") or "").strip()
    if not token_nonce or token_nonce != expected_nonce:
        raise HTTPException(status_code=401, detail="ID token nonce mismatch.")

    return claims


def create_web_app(
    settings: AgentSettings,
    readiness: dict[str, object] | None = None,
) -> FastAPI:
    """Build the FastAPI app carrying the adapter's own (non-SDK) routes."""
    app = FastAPI(title="Teams AI Agent Adapter", docs_url=None, redoc_url=None)
    readiness_payload = readiness if readiness is not None else build_readiness(settings)

    @app.get("/healthz")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/readyz")
    async def ready() -> JSONResponse:
        status = 200 if readiness_payload.get("status") == "ready" else 503
        return JSONResponse(readiness_payload, status_code=status)

    @app.get("/rag-assets/{path:path}")
    async def asset(path: str, request: Request) -> Response:
        try:
            resolved = resolve_asset(
                path,
                request.query_params.get("expires"),
                request.query_params.get("signature"),
                settings,
            )
            content, content_type = render_teams_image(resolved, settings)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Not Found") from error
        except ValueError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Cache-Control": f"private, max-age={settings.asset_url_ttl_seconds}",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/rag-sources/{path:path}")
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

    @app.get("/sources/login")
    async def viewer_login_page(request: Request) -> Response:
        redirect_url = request.query_params.get("redirect_url") or request.query_params.get("redirect") or ""
        # If user is already authenticated through gateway headers or existing valid cookie
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

    @app.get("/sources/auth/login")
    async def viewer_auth_login(request: Request) -> Response:
        redirect_url = request.query_params.get("redirect_url") or request.query_params.get("redirect") or ""
        auth_subject = _authenticated_viewer_subject(request, settings)
        if auth_subject:
            target = redirect_url if _is_safe_redirect_target(redirect_url, settings.public_base_url) else "/healthz"
            return Response(status_code=302, headers={"Location": target})

        tenant_id = settings.tenant_id or "common"
        client_id = settings.client_id
        if not client_id:
            # When SSO is unconfigured in local dev/mock without client_id, fallback to login page with prompt
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

    @app.get("/sources/auth/callback")
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
            # If an id_token string is provided by the exchanger, perform full OIDC verification
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
                # If mock/adapter dictionary is returned directly, validate claims if present
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
        # Do not overwrite existing valid membership groups with empty groups
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
        # One-time consumption: delete SSO auth session cookie
        resp.delete_cookie("sso_auth_session")
        return resp

    @app.post("/sources/login")
    async def viewer_login_submit(request: Request) -> Response:
        form_data: dict[str, Any] = {}
        raw_body = await request.body()
        if raw_body:
            content_type = request.headers.get("content-type", "").lower()
            if "application/json" in content_type:
                try:
                    import json

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

    @app.post("/sources/logout")
    async def viewer_logout() -> Response:
        resp = Response(content=b'{"status":"ok"}', media_type="application/json")
        resp.delete_cookie("teams_viewer_token")
        return resp

    return app


def _authenticated_viewer_subject(request: Request, settings: AgentSettings) -> str | None:
    """Extract and cryptographically verify login identity.

    External requests cannot spoof identity:
    - X-Viewer-Subject is trusted only if accompanied by a verified X-Gateway-Secret.
    - Bearer tokens are cryptographically verified using HMAC asset_signing_key or JWT signature.
    - Query parameter `token` / `viewer_token` is cryptographically verified via HMAC.
    - Session cookie `teams_viewer_token` is cryptographically verified via HMAC.
    - Unsigned / unverified tokens are rejected.
    """
    import hmac

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
            # If secret is missing or mismatched, header is untrusted and ignored

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



def build_http_adapter(
    settings: AgentSettings,
    readiness: dict[str, object] | None = None,
) -> FastAPIAdapter:
    """Wrap the adapter's FastAPI app so the Teams SDK can mount onto it."""
    return FastAPIAdapter(app=create_web_app(settings, readiness))
