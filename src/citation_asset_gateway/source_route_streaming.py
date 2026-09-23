"""Source document delivery helpers and route registration."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .settings_contract import CitationGatewaySettings
from .source_api import (
    SourceApiError,
    fetch_original_source_file,
    fetch_source_preview,
    stream_original_source_file,
)
from .source_links import (
    CitationViewerContext,
    authorize_original_open,
    build_original_url,
    citation_source_groups,
    citation_source_tenant_id,
    resolve_source_file,
    source_media_type,
)
from .source_route_auth import authenticated_viewer_subject, seed_gateway_membership
from .source_route_payloads import (
    citation_html_response_headers,
    fallback_preview_markdown,
    preview_evidence,
)
from .source_release_preview import (
    release_preview_payload,
    resolve_release_citation_preview,
)
from .source_storage import (
    SourceDocumentUnavailable,
    fetch_release_source_document,
)
from .source_viewer import render_source_document_html, render_source_markdown_html

logger = logging.getLogger(__name__)


def login_redirect_if_unauthenticated(
    request: Request,
    auth_subject: str | None,
    settings: CitationGatewaySettings | None = None,
) -> Response | None:
    """Redirect browser HTML opens to login when viewer auth is missing.

    Local ``allow_unauthenticated_requests`` trusts verified signed URLs, so the
    login interstitial is skipped and callers surface 403 for bad signatures.
    """

    if settings is not None and settings.allow_unauthenticated_requests:
        return None
    accept = request.headers.get("accept", "").lower()
    if "text/html" in accept and not auth_subject:
        redirect_target = f"/sources/login?redirect_url={quote(str(request.url))}"
        return Response(status_code=302, headers={"Location": redirect_target})
    return None


async def load_citation_document(
    settings: CitationGatewaySettings,
    *,
    source_ref_id: str,
    payload: dict,
    source_tenant_id: str | None,
) -> tuple[str | None, str | None]:
    release_id = str(payload.get("releaseId") or "")
    source_path = str(payload.get("sourcePath") or "")
    if not release_id or not source_path:
        return None, "此引用沒有可驗證的文件版本；下方內容僅為已授權的引用片段。"
    try:
        document = await asyncio.to_thread(
            fetch_release_source_document,
            settings,
            release_id=release_id,
            source_path=source_path,
            tenant_id=source_tenant_id,  # type: ignore[arg-type]
        )
        return document, None
    except SourceDocumentUnavailable as error:
        logger.warning(
            "citation_full_source_unavailable source_ref_id=%s reason=%s",
            source_ref_id,
            error,
        )
        return None, "完整文件目前無法載入；下方內容僅為已授權的引用片段。"


def raise_original_source_api_error(error: SourceApiError) -> Response:
    if error.status == 416:
        headers = dict(error.headers)
        headers.setdefault("Cache-Control", "private, no-store")
        return Response(content=error.body, status_code=416, headers=headers)
    detail = str(error)
    status = 502
    if error.status in (401, 403) or "HTTP 403" in detail or "HTTP 401" in detail:
        status = 403
    elif error.status == 404 or "HTTP 404" in detail:
        status = 404
    elif 400 <= error.status < 500:
        status = error.status
    raise HTTPException(status_code=status, detail="Original source unavailable.") from error


async def handle_source_preview(
    source_ref_id: str,
    request: Request,
    settings: CitationGatewaySettings,
) -> Response:
    auth_subject = authenticated_viewer_subject(request, settings)
    seed_gateway_membership(request, settings, subject=auth_subject)
    try:
        viewer = authorize_original_open(
            source_ref_id,
            request.query_params.get("expires"),
            request.query_params.get("signature"),
            settings,
            subject=request.query_params.get("subject"),
            tenant_id=request.query_params.get("tenantId"),
            authenticated_subject=auth_subject,
        )
        payload = await fetch_source_preview(
            settings,
            source_ref_id=source_ref_id,
            subject=viewer.subject,
            tenant_id=citation_source_tenant_id("playground", viewer.tenant_id),
            groups=citation_source_groups("playground", viewer.tenant_id, viewer.groups),
        )
    except PermissionError as error:
        redirect = login_redirect_if_unauthenticated(request, auth_subject, settings)
        if redirect is not None:
            return redirect
        raise HTTPException(status_code=403, detail=str(error)) from error
    except SourceApiError as error:
        payload = _release_preview_fallback(settings, source_ref_id, viewer, error)
        if payload is None:
            status = error.status if error.status in {403, 404} else 502
            raise HTTPException(
                status_code=status, detail="Source preview unavailable."
            ) from error

    return await _render_citation_preview(source_ref_id, settings, viewer, payload)


def _release_preview_fallback(
    settings: CitationGatewaySettings,
    source_ref_id: str,
    viewer: CitationViewerContext,
    error: SourceApiError,
) -> dict[str, object] | None:
    logger.warning(
        "source_preview_source_api_failed source_ref_id=%s status=%s error=%s",
        source_ref_id,
        error.status,
        error,
    )
    if error.status in {401, 403}:
        return None
    tenant_id = (
        citation_source_tenant_id("playground", viewer.tenant_id)
        or settings.asset_gcs_tenant_id
        or "default"
    )
    preview = resolve_release_citation_preview(
        settings,
        source_ref_id=source_ref_id,
        tenant_id=str(tenant_id),
    )
    if preview is None:
        return None
    return release_preview_payload(preview)


async def _render_citation_preview(
    source_ref_id: str,
    settings: CitationGatewaySettings,
    viewer: CitationViewerContext,
    payload: dict,
) -> Response:
    source_tenant_id = citation_source_tenant_id("playground", viewer.tenant_id)
    release_id = str(payload.get("releaseId") or "")
    source_document, fallback_message = await load_citation_document(
        settings,
        source_ref_id=source_ref_id,
        payload=payload,
        source_tenant_id=source_tenant_id,
    )
    actions = payload.get("actions")
    can_download = bool(isinstance(actions, dict) and actions.get("canDownloadOriginal"))
    download_url = (
        build_original_url(source_ref_id, settings, viewer=viewer) if can_download else None
    )
    rendered = render_source_markdown_html(
        source_document or fallback_preview_markdown(payload),
        settings,
        fallback_title=str(payload.get("title") or "引用來源"),
        release_id=release_id or None,
        evidence=preview_evidence(payload),
        status_message=fallback_message or str(payload.get("message") or ""),
        mapping_status=str(payload.get("mappingStatus") or ""),
        download_url=download_url,
    )
    return Response(
        content=rendered,
        media_type="text/html; charset=utf-8",
        headers=citation_html_response_headers(),
    )


async def handle_source_document(
    path: str,
    request: Request,
    settings: CitationGatewaySettings,
) -> Response:
    auth_subject = authenticated_viewer_subject(request, settings)
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
        want_raw = request.query_params.get("raw", "").lower() in {"1", "true", "yes"}
        if not want_raw and resolved.suffix.lower() in {".md", ".markdown", ".txt"}:
            content = render_source_document_html(resolved, settings)
            content_type = "text/html; charset=utf-8"
        else:
            content = resolved.read_bytes()
            content_type = source_media_type(resolved)
    except PermissionError as error:
        redirect = login_redirect_if_unauthenticated(request, auth_subject, settings)
        if redirect is not None:
            return redirect
        raise HTTPException(status_code=403, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Not Found") from error

    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": f"private, max-age={settings.asset_url_ttl_seconds}",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": ("inline; filename*=UTF-8''" + quote(resolved.name)),
        },
    )


async def handle_original_source_document(
    source_ref_id: str,
    request: Request,
    settings: CitationGatewaySettings,
) -> Response:
    auth_subject = authenticated_viewer_subject(request, settings)
    # Playground/gateway opens authenticate the subject via shared secret but
    # may arrive before a chat turn refreshes viewer membership. Seed a
    # short-lived public membership so lab testing does not require M365.
    seed_gateway_membership(request, settings, subject=auth_subject)
    try:
        viewer = authorize_original_open(
            source_ref_id,
            request.query_params.get("expires"),
            request.query_params.get("signature"),
            settings,
            subject=request.query_params.get("subject"),
            tenant_id=request.query_params.get("tenantId"),
            authenticated_subject=auth_subject,
        )
        if request.method == "HEAD":
            return await _head_original_source(settings, source_ref_id, viewer, request)
        return await _stream_original_source(settings, source_ref_id, viewer, request)
    except PermissionError as error:
        redirect = login_redirect_if_unauthenticated(request, auth_subject, settings)
        if redirect is not None:
            return redirect
        raise HTTPException(status_code=403, detail=str(error)) from error
    except SourceApiError as error:
        return raise_original_source_api_error(error)


async def _head_original_source(
    settings: CitationGatewaySettings,
    source_ref_id: str,
    viewer: CitationViewerContext,
    request: Request,
) -> Response:
    upstream = await fetch_original_source_file(
        settings,
        source_ref_id=source_ref_id,
        subject=viewer.subject,
        tenant_id=citation_source_tenant_id("playground", viewer.tenant_id),
        groups=citation_source_groups("playground", viewer.tenant_id, viewer.groups),
        accept=request.headers.get("accept"),
        method="HEAD",
    )
    headers = dict(upstream.headers)
    headers["Cache-Control"] = "private, no-store"
    return Response(status_code=upstream.status, headers=headers)


async def _stream_original_source(
    settings: CitationGatewaySettings,
    source_ref_id: str,
    viewer: CitationViewerContext,
    request: Request,
) -> Response:
    upstream_status, upstream_headers, upstream_stream = await stream_original_source_file(
        settings,
        source_ref_id=source_ref_id,
        subject=viewer.subject,
        tenant_id=citation_source_tenant_id("playground", viewer.tenant_id),
        groups=citation_source_groups("playground", viewer.tenant_id, viewer.groups),
        range_header=request.headers.get("range"),
        accept=request.headers.get("accept"),
    )
    headers = dict(upstream_headers)
    headers.setdefault("Cache-Control", "private, no-store")
    return StreamingResponse(
        upstream_stream,
        status_code=upstream_status,
        headers=headers,
    )


def register_source_delivery_routes(router: APIRouter, settings: CitationGatewaySettings) -> None:
    """Register citation, local document, and original-file delivery endpoints."""

    @router.get("/rag-citations/{source_ref_id}")
    async def source_preview(source_ref_id: str, request: Request) -> Response:
        return await handle_source_preview(source_ref_id, request, settings)

    @router.get("/rag-sources/{path:path}")
    async def source_document(path: str, request: Request) -> Response:
        return await handle_source_document(path, request, settings)

    @router.api_route("/rag-originals/{source_ref_id}", methods=["GET", "HEAD"])
    async def original_source_document(source_ref_id: str, request: Request) -> Response:
        return await handle_original_source_document(source_ref_id, request, settings)
