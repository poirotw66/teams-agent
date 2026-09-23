"""Backoffice BFF routes that surface Agent knowledge release sync status."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException

logger = logging.getLogger(__name__)


def register_agent_knowledge_sync_routes(
    app: FastAPI,
    *,
    resolved_settings: Any,
    current_actor: Callable[..., Any],
    require_capability: Callable[[Any, str], None],
) -> None:
    """Expose Agent knowledge sync admin APIs to console-v2.

    Preferred console paths:
    - ``GET  /api/console/agent-knowledge/status``
    - ``POST /api/console/agent-knowledge/sync``

    Legacy aliases (same handlers):
    - ``GET  /api/agent/knowledge-status``
    - ``POST /api/agent/knowledge-sync``
    """

    async def _status(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.knowledge.read")
        return await _call_agent(
            resolved_settings,
            method="GET",
            path="/admin/knowledge-status",
        )

    async def _sync(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.sync.write")
        return await _call_agent(
            resolved_settings,
            method="POST",
            path="/admin/knowledge-sync",
        )

    app.get(
        "/api/console/agent-knowledge/status",
        operation_id="get_console_agent_knowledge_status",
    )(_status)
    app.post(
        "/api/console/agent-knowledge/sync",
        operation_id="post_console_agent_knowledge_sync",
    )(_sync)
    # Legacy aliases kept for compatibility; excluded from OpenAPI to avoid
    # duplicate operationIds with the canonical console paths.
    app.get("/api/agent/knowledge-status", include_in_schema=False)(_status)
    app.post("/api/agent/knowledge-sync", include_in_schema=False)(_sync)


async def _call_agent(
    settings: Any,
    *,
    method: str,
    path: str,
) -> dict[str, object]:
    agent_api_url = getattr(settings, "agent_api_url", None)
    if not agent_api_url:
        raise HTTPException(
            status_code=503,
            detail="Agent API URL is not configured (AGENT_API_URL).",
        )
    base_url = str(agent_api_url).rstrip("/")
    headers: dict[str, str] = {}
    # Prefer Google ID token for private Cloud Run Agent (same as Portal reload).
    auth_mode = str(
        getattr(settings, "agent_api_auth_mode", None)
        or os.environ.get("KNOWLEDGE_PORTAL_AGENT_API_AUTH_MODE")
        or os.environ.get("AGENT_API_AUTH_MODE")
        or ""
    ).strip().upper()
    if auth_mode in {"", "GOOGLE_ID_TOKEN", "GOOGLE-ID-TOKEN"}:
        try:
            from ..knowledge_bridge.client import _fetch_google_id_token

            identity_token = await asyncio.to_thread(_fetch_google_id_token, base_url)
            headers["Authorization"] = f"Bearer {identity_token}"
        except Exception as error:
            # Fall back to shared service token for local / non-GCP Agent targets.
            logger.warning(
                "Google ID token for Agent unavailable (%s); trying service token.",
                error,
            )
            auth_mode = "BEARER"
    if auth_mode == "BEARER" or "Authorization" not in headers:
        token = (
            os.environ.get("AGENT_SERVICE_TOKEN")
            or os.environ.get("AGENT_RELOAD_TOKEN")
            or getattr(settings, "service_token", "")
            or ""
        )
        if token:
            headers["Authorization"] = f"Bearer {token}"
    url = f"{base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(method, url, headers=headers)
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Agent knowledge sync endpoint unreachable: {error}",
        ) from error
    if response.status_code >= 400:
        detail: object
        try:
            payload = response.json()
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        except ValueError:
            detail = response.text[:300] or response.reason_phrase
        raise HTTPException(status_code=response.status_code, detail=detail)
    body = response.json()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=502,
            detail="Agent knowledge sync response was not a JSON object.",
        )
    return body
