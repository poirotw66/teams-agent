"""Backoffice BFF routes that surface Agent knowledge release sync status."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException


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

    app.get("/api/console/agent-knowledge/status")(_status)
    app.post("/api/console/agent-knowledge/sync")(_sync)
    app.get("/api/agent/knowledge-status")(_status)
    app.post("/api/agent/knowledge-sync")(_sync)


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
    token = (
        os.environ.get("AGENT_SERVICE_TOKEN")
        or os.environ.get("AGENT_RELOAD_TOKEN")
        or getattr(settings, "service_token", "")
        or ""
    )
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{str(agent_api_url).rstrip('/')}{path}"
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
