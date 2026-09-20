"""Source viewer and enterprise SSO routes for Teams Adapter.

Provides endpoints for viewing referenced RAG sources, authenticating via
Entra ID SSO with CSRF protection, and session cookie management (Spec A05-T1).

Auth, streaming, and payload helpers live in sibling modules; this module owns
route registration and stable public imports.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response

from .settings_contract import CitationGatewaySettings
from .source_api import (
    fetch_original_source_file,
    fetch_source_preview,
    stream_original_source_file,
)
from .source_links import create_viewer_token, verify_viewer_token
from .source_route_auth import (
    IdTokenVerifier,
    authenticated_viewer_subject,
    encode_signed_blob,
    is_safe_redirect_target,
    mark_sso_state_consumed,
    parse_sso_callback_state,
    parse_sso_session_cookie,
    resolve_sso_identity,
    set_id_token_verifier,
    sso_signing_secret,
)
from .source_route_payloads import build_entra_authorize_url, build_viewer_login_page_html
from .source_route_streaming import register_source_delivery_routes
from .source_storage import fetch_release_source_document
from .viewer_sessions import get_viewer_membership_store

# Stable private aliases for server.py / __all__ re-exports.
_authenticated_viewer_subject = authenticated_viewer_subject
_is_safe_redirect_target = is_safe_redirect_target
_mark_sso_state_consumed = mark_sso_state_consumed


def _safe_redirect_location(redirect_url: str, settings: CitationGatewaySettings) -> str:
    if is_safe_redirect_target(redirect_url, settings.public_base_url):
        return redirect_url
    return "/healthz"


def _set_viewer_token_cookie(response: Response, token: str, settings: CitationGatewaySettings) -> None:
    response.set_cookie(
        "teams_viewer_token",
        token,
        max_age=settings.asset_url_ttl_seconds,
        httponly=True,
        samesite="lax",
    )


async def _parse_login_form(request: Request) -> dict[str, Any]:
    form_data: dict[str, Any] = {}
    raw_body = await request.body()
    if not raw_body:
        return form_data
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}
    from urllib.parse import parse_qs

    try:
        parsed_qs = parse_qs(raw_body.decode("utf-8"))
        return {key: values[0] for key, values in parsed_qs.items()}
    except (ValueError, UnicodeDecodeError):
        return {}


def _register_viewer_auth_routes(router: APIRouter, settings: CitationGatewaySettings) -> None:
    @router.get("/sources/login")
    async def viewer_login_page(request: Request) -> Response:
        redirect_url = (
            request.query_params.get("redirect_url") or request.query_params.get("redirect") or ""
        )
        auth_subject = authenticated_viewer_subject(request, settings)
        if auth_subject:
            return Response(
                status_code=302,
                headers={"Location": _safe_redirect_location(redirect_url, settings)},
            )

        token = request.query_params.get("token") or request.query_params.get("viewer_token")
        if token and str(token).strip():
            payload = verify_viewer_token(str(token).strip(), settings)
            if payload and payload.get("sub"):
                resp = Response(
                    status_code=302,
                    headers={"Location": _safe_redirect_location(redirect_url, settings)},
                )
                _set_viewer_token_cookie(resp, str(token).strip(), settings)
                return resp

        page = build_viewer_login_page_html(redirect_url)
        return Response(content=page.encode("utf-8"), media_type="text/html; charset=utf-8")

    @router.get("/sources/auth/login")
    async def viewer_auth_login(request: Request) -> Response:
        return _start_viewer_sso_login(request, settings)

    @router.get("/sources/auth/callback")
    async def viewer_auth_callback(request: Request) -> Response:
        return await _complete_viewer_sso_login(request, settings)

    @router.post("/sources/login")
    async def viewer_login_submit(request: Request) -> Response:
        form_data = await _parse_login_form(request)
        token = str(form_data.get("token") or "").strip()
        redirect_url = str(form_data.get("redirect_url") or "").strip()
        payload = verify_viewer_token(token, settings)
        if not payload or not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid or expired viewer token.")
        resp = Response(
            status_code=302,
            headers={"Location": _safe_redirect_location(redirect_url, settings)},
        )
        _set_viewer_token_cookie(resp, token, settings)
        return resp

    @router.post("/sources/logout")
    async def viewer_logout() -> Response:
        resp = Response(content=b'{"status":"ok"}', media_type="application/json")
        resp.delete_cookie("teams_viewer_token")
        return resp


def _start_viewer_sso_login(request: Request, settings: CitationGatewaySettings) -> Response:
    redirect_url = (
        request.query_params.get("redirect_url") or request.query_params.get("redirect") or ""
    )
    auth_subject = authenticated_viewer_subject(request, settings)
    if auth_subject:
        return Response(
            status_code=302,
            headers={"Location": _safe_redirect_location(redirect_url, settings)},
        )

    tenant_id = settings.tenant_id or "common"
    client_id = settings.client_id
    if not client_id:
        return Response(
            status_code=302,
            headers={
                "Location": f"/sources/login?redirect_url={quote(redirect_url)}&error=sso_unconfigured"
            },
        )

    base_url = settings.public_base_url or str(request.base_url).rstrip("/")
    callback_url = f"{base_url}/sources/auth/callback"
    state_id = uuid.uuid4().hex
    nonce = uuid.uuid4().hex
    secret = sso_signing_secret(settings)
    state_param = encode_signed_blob(
        {"state_id": state_id, "redirect_url": redirect_url, "ts": time.time()},
        secret,
    )
    session_cookie_val = encode_signed_blob(
        {"state_id": state_id, "nonce": nonce, "ts": time.time()},
        secret,
    )
    auth_url = build_entra_authorize_url(
        tenant_id=tenant_id,
        client_id=client_id,
        callback_url=callback_url,
        state_param=state_param,
        nonce=nonce,
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


async def _complete_viewer_sso_login(request: Request, settings: CitationGatewaySettings) -> Response:
    code = request.query_params.get("code")
    state_param = request.query_params.get("state") or ""
    if not code or not state_param:
        raise HTTPException(status_code=400, detail="Missing authorization code or state.")

    secret = sso_signing_secret(settings)
    state_data = parse_sso_callback_state(state_param, secret)
    state_id = str(state_data.get("state_id") or "")
    session_data = parse_sso_session_cookie(request.cookies.get("sso_auth_session"), secret)

    if not state_id or session_data.get("state_id") != state_id:
        raise HTTPException(status_code=403, detail="SSO state does not match login session.")
    if not mark_sso_state_consumed(state_id):
        raise HTTPException(status_code=403, detail="SSO state has already been consumed.")

    expected_nonce = str(session_data.get("nonce") or "")
    target = _safe_redirect_location(str(state_data.get("redirect_url") or ""), settings)
    base_url = settings.public_base_url or str(request.base_url).rstrip("/")
    callback_url = f"{base_url}/sources/auth/callback"
    tenant_id = settings.tenant_id or "common"

    subject, groups, tenant_id = await resolve_sso_identity(
        request,
        settings,
        code=code,
        callback_url=callback_url,
        expected_nonce=expected_nonce,
        tenant_id=tenant_id,
    )

    store = get_viewer_membership_store(settings)
    existing_membership = store.resolve(subject)
    if not groups and existing_membership and existing_membership.groups:
        groups = list(existing_membership.groups)
    store.remember(subject, groups=groups, tenant_id=tenant_id)

    viewer_token = create_viewer_token(subject, settings, tenant_id=tenant_id)
    resp = Response(status_code=302, headers={"Location": target})
    _set_viewer_token_cookie(resp, viewer_token, settings)
    resp.delete_cookie("sso_auth_session")
    return resp


def create_source_router(
    settings: CitationGatewaySettings,
    *,
    id_token_verifier: IdTokenVerifier | None = None,
) -> APIRouter:
    """Create router with RAG source document and SSO authentication endpoints."""
    if id_token_verifier is not None:
        set_id_token_verifier(id_token_verifier)
    router = APIRouter()
    register_source_delivery_routes(router, settings)
    _register_viewer_auth_routes(router, settings)
    return router


__all__ = [
    "_authenticated_viewer_subject",
    "_is_safe_redirect_target",
    "_mark_sso_state_consumed",
    "create_source_router",
    "fetch_original_source_file",
    "fetch_release_source_document",
    "fetch_source_preview",
    "stream_original_source_file",
]
