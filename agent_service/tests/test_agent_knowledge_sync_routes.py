"""Tests for Backoffice Agent knowledge sync BFF routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ai_ops_backoffice.routers.agent_knowledge_sync_routes import (
    register_agent_knowledge_sync_routes,
)
from operations_core.access import ActorContext


def _actor() -> ActorContext:
    return ActorContext("u1", "Tester", "KNOWLEDGE_ADMIN", ("it",))


def _app() -> FastAPI:
    app = FastAPI()
    settings = type(
        "Settings",
        (),
        {"agent_api_url": "http://agent.example", "service_token": "token"},
    )()

    def current_actor() -> ActorContext:
        return _actor()

    def require_capability(actor: ActorContext, capability: str) -> None:
        if not actor.has_capability(capability):
            raise HTTPException(status_code=403, detail=capability)

    register_agent_knowledge_sync_routes(
        app,
        resolved_settings=settings,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    return app


def test_status_route_proxies_agent_payload() -> None:
    app = _app()
    client = TestClient(app)
    upstream = {
        "currentReleaseId": "release-1",
        "sync": {
            "cloudActiveReleaseId": "release-1",
            "mirroredReleaseId": "release-1",
            "loadedReleaseId": "release-1",
            "alignedWithCloud": True,
            "syncState": "IN_SYNC",
            "runtimeInventoryComplete": True,
        },
    }
    with patch(
        "ai_ops_backoffice.routers.agent_knowledge_sync_routes._call_agent",
        new=AsyncMock(return_value=upstream),
    ) as mocked:
        response = client.get("/api/console/agent-knowledge/status")
    assert response.status_code == 200
    assert response.json()["sync"]["alignedWithCloud"] is True
    mocked.assert_awaited_once()
    assert mocked.await_args.kwargs["path"] == "/admin/knowledge-status"


def test_sync_route_proxies_post() -> None:
    app = _app()
    client = TestClient(app)
    upstream = {
        "cloudActiveReleaseId": "release-2",
        "mirroredReleaseId": "release-2",
        "loadedReleaseId": "release-1",
        "alignedWithCloud": False,
        "syncState": "IN_SYNC",
    }
    with patch(
        "ai_ops_backoffice.routers.agent_knowledge_sync_routes._call_agent",
        new=AsyncMock(return_value=upstream),
    ) as mocked:
        response = client.post("/api/console/agent-knowledge/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["alignedWithCloud"] is False
    assert body["loadedReleaseId"] == "release-1"
    assert mocked.await_args.kwargs["method"] == "POST"
    assert mocked.await_args.kwargs["path"] == "/admin/knowledge-sync"


def test_legacy_agent_status_alias_still_works() -> None:
    app = _app()
    client = TestClient(app)
    with patch(
        "ai_ops_backoffice.routers.agent_knowledge_sync_routes._call_agent",
        new=AsyncMock(return_value={"ok": True}),
    ):
        response = client.get("/api/agent/knowledge-status")
    assert response.status_code == 200
    assert response.json()["ok"] is True
