"""FastAPI routes for /api/knowledge/* (Portal BFF namespace)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from agent_service.operations.access import ActorContext

from .capabilities import capability_for_portal_path, has_knowledge_capability
from .client import KnowledgePortalClient
from .errors import KnowledgeBridgeError, assert_allowlisted


def build_knowledge_router(
    *,
    client: KnowledgePortalClient,
    current_actor: Callable[..., ActorContext],
    enabled: bool,
) -> APIRouter:
    router = APIRouter(tags=["knowledge-bridge"])

    def _correlation(x_correlation_id: str | None = Header(default=None)) -> str:
        value = (x_correlation_id or "").strip()
        if value and len(value) <= 128 and all(ch.isalnum() or ch in "-_" for ch in value):
            return value
        return uuid.uuid4().hex

    def _require_enabled() -> None:
        if not enabled or not client.configured:
            raise KnowledgeBridgeError(
                code="KNOWLEDGE_BRIDGE_DISABLED",
                message="知識整合尚未啟用。請使用核准的整合設定後再試。",
                status_code=503,
            )

    @router.get("/status")
    async def knowledge_bridge_status(
        actor: ActorContext = Depends(current_actor),
        correlation_id: str = Depends(_correlation),
    ) -> dict[str, Any]:
        _ = actor
        return {
            "enabled": bool(enabled and client.configured),
            "namespace": "/api/knowledge",
            "correlationId": correlation_id,
            "note": (
                "Portal UI is not a separate BU product entry. "
                "Use this namespace for knowledge operations."
            ),
        }

    @router.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    async def knowledge_proxy(
        full_path: str,
        request: Request,
        actor: ActorContext = Depends(current_actor),
        correlation_id: str = Depends(_correlation),
    ) -> Response:
        _require_enabled()
        # Reject browser-forged Portal identity on the BFF surface.
        for banned in (
            "x-portal-user-id",
            "x-portal-user-name",
            "x-portal-role",
            "x-portal-owner-units",
        ):
            if banned in request.headers:
                raise KnowledgeBridgeError(
                    code="KNOWLEDGE_FORGED_PORTAL_IDENTITY",
                    message="不可透過瀏覽器指定知識服務身分。",
                    status_code=400,
                    correlation_id=correlation_id,
                )

        relative = assert_allowlisted(full_path)
        capability = capability_for_portal_path(request.method, relative)
        if not has_knowledge_capability(actor, capability):
            raise KnowledgeBridgeError(
                code="KNOWLEDGE_FORBIDDEN",
                message=f"需要權限：{capability}。請聯絡知識管理者。",
                status_code=403,
                correlation_id=correlation_id,
                details={"requiredCapability": capability},
            )

        content_type = request.headers.get("content-type")
        body = await request.body()
        json_body = None
        content = None
        forward_content_type = None
        if body:
            if content_type and "application/json" in content_type:
                import json

                try:
                    json_body = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise KnowledgeBridgeError(
                        code="KNOWLEDGE_INVALID_JSON",
                        message="請求內容不是有效的 JSON。",
                        status_code=400,
                        correlation_id=correlation_id,
                    ) from exc
            else:
                content = body
                forward_content_type = content_type

        upstream = await client.request(
            method=request.method,
            relative_path=relative,
            actor=actor,
            correlation_id=correlation_id,
            query=dict(request.query_params),
            json_body=json_body,
            content=content,
            content_type=forward_content_type,
        )
        return _to_response(upstream, correlation_id=correlation_id)

    return router


def _to_response(upstream: Any, *, correlation_id: str) -> Response:
    status = int(upstream.status_code)
    media_type = upstream.headers.get("content-type") or "application/json"
    if status >= 400:
        payload = _safe_upstream_error(upstream, correlation_id=correlation_id, status=status)
        return JSONResponse(status_code=status, content=payload)
    if "application/json" in media_type:
        return JSONResponse(status_code=status, content=upstream.json())
    headers = {}
    for key in ("content-disposition", "content-type", "cache-control"):
        value = upstream.headers.get(key)
        if value:
            headers[key] = value
    return StreamingResponse(
        iter([upstream.content]),
        status_code=status,
        media_type=media_type,
        headers=headers,
    )


def _safe_upstream_error(upstream: Any, *, correlation_id: str, status: int) -> dict[str, Any]:
    code = "KNOWLEDGE_UPSTREAM_ERROR"
    message = "知識服務請求失敗。"
    details: dict[str, Any] = {}
    try:
        payload = upstream.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail and len(detail) < 300:
            message = detail
        elif isinstance(payload.get("error"), dict):
            err = payload["error"]
            code = str(err.get("code") or code)
            message = str(err.get("message") or message)
            if isinstance(err.get("details"), dict):
                details = err["details"]
    if status == 401:
        code = "KNOWLEDGE_UPSTREAM_UNAUTHORIZED"
        message = "知識服務拒絕服務身分或委派身分。"
    elif status == 403:
        code = "KNOWLEDGE_UPSTREAM_FORBIDDEN"
    elif status == 404:
        code = "KNOWLEDGE_NOT_FOUND"
        message = "找不到可存取的知識資源。"
    elif status == 409:
        code = "KNOWLEDGE_VERSION_CONFLICT"
        message = "這份文件已被更新，請重新載入後再儲存。"
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": status in {429, 502, 503, 504},
            "correlationId": correlation_id,
            "details": details,
        }
    }
