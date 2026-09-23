"""Tests for FOLLOW_CLOUD hot-reload and Agent knowledge sync BFF."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException

from agent_service.deps_sync import apply_follow_cloud_mirror_reload
from agent_service.knowledge_release import ResolvedKnowledgeIndex
from agent_service.release_artifacts import inspect_index_artifact
from agent_service.settings import RagSettings
from ai_ops_backoffice.routers.agent_knowledge_sync_routes import (
    register_agent_knowledge_sync_routes,
)
from knowledge_portal.models import ReleaseManifestEntry
from knowledge_portal.service_catalog_artifact import (
    SERVICE_CATALOG_RELATIVE_PATH,
    write_service_catalog_artifact,
)


def _settings(tmp_path: Path) -> RagSettings:
    return RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_cache_dir=tmp_path / "cache",
        knowledge_release_tenant_id="tenant-a",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
    )


def test_follow_cloud_reload_refuses_pinned_selection(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    object.__setattr__(settings, "knowledge_release_selection_mode", "PINNED")
    object.__setattr__(settings, "knowledge_active_release_id", "release-pin")
    app = FastAPI()
    app.state.knowledge_release_id = "release-old"

    assert (
        apply_follow_cloud_mirror_reload(app, settings, release_id="release-new")
        is False
    )
    assert app.state.knowledge_release_id == "release-old"


def test_follow_cloud_reload_swaps_when_mirror_ready(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = FastAPI()
    app.state.knowledge_release_id = "release-old"
    app.state.hybrid_settings = settings
    app.state.rag_model = object()
    app.state.knowledge_router = SimpleNamespace(
        update_service=lambda *args, **kwargs: None,
        remove_service=lambda *args, **kwargs: None,
    )
    syncer = SimpleNamespace(set_loaded_release_id=MagicMock())
    app.state.knowledge_release_syncer = syncer

    release_id = "release-new"
    release_root = tmp_path / "cache" / "tenants" / "tenant-a" / "releases"
    index_path = release_root / release_id / "index" / "chunks.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "embeddingModel": "model-a",
                "chunks": [
                    {
                        "chunk_id": "1",
                        "source_path": "sources/doc.md",
                        "document_id": "doc",
                        "version_id": "v1",
                        "allowed_groups": ["grp_public"],
                        "vector": [0.1, 0.2],
                        "content": "x",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifact = inspect_index_artifact(index_path)
    resolved = ResolvedKnowledgeIndex(
        index_path=index_path,
        release_id=release_id,
        source="gcs_mirror",
        artifact=artifact,
        release_dir=release_root,
    )

    with (
        patch(
            "agent_service.deps_sync.resolve_knowledge_index",
            return_value=resolved,
        ),
        patch(
            "agent_service.deps_sync.load_validated_release_index",
            return_value=(SimpleNamespace(chunks=[1, 2]), artifact),
        ),
        patch("agent_service.deps_sync.RagAgent", return_value=object()),
        patch(
            "agent_service.deps_sync.build_knowledge_service",
            return_value=object(),
        ),
        patch(
            "agent_service.deps_sync.configure_service_scope_from_release",
        ),
        patch(
            "agent_service.deps_sync.manifest_file_search_store",
            return_value=None,
        ),
    ):
        swapped = apply_follow_cloud_mirror_reload(
            app,
            settings,
            release_id=release_id,
        )

    assert swapped is True
    assert app.state.knowledge_release_id == release_id
    assert app.state.knowledge_index_source == "gcs_mirror"
    syncer.set_loaded_release_id.assert_called_with(release_id)


def test_service_catalog_artifact_written_under_catalog_prefix(tmp_path: Path) -> None:
    release_dir = tmp_path / "release-1"
    release_dir.mkdir()
    path = write_service_catalog_artifact(
        release_dir,
        release_id="release-1",
        tenant_id="tenant-a",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-vpn",
                version_id="v1",
                version_number=1,
                title="VPN 連線",
                content_hash="abc",
                source_path="sources/doc-vpn.md",
                source_aliases=["VPN", "FortiClient"],
                acl_groups=["grp_public"],
            )
        ],
    )
    assert path.as_posix().endswith(SERVICE_CATALOG_RELATIVE_PATH)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["services"][0]["serviceId"] == "doc-vpn"
    assert "VPN" in payload["services"][0]["aliases"]


@pytest.mark.asyncio
async def test_agent_knowledge_status_bff_forwards_to_agent(
    tmp_path: Path,
) -> None:
    app = FastAPI()
    settings = SimpleNamespace(
        agent_api_url="http://agent.example",
        service_token="secret-token",
    )

    def require_capability(_actor: object, capability: str) -> None:
        assert capability == "ops.knowledge.read"

    register_agent_knowledge_sync_routes(
        app,
        resolved_settings=settings,
        current_actor=lambda: SimpleNamespace(role="SYSTEM_ADMIN"),
        require_capability=require_capability,
    )

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "sync": {
            "cloudActiveReleaseId": "r1",
            "mirroredReleaseId": "r1",
            "loadedReleaseId": "r1",
            "alignedWithCloud": True,
            "qaSnapshotComplete": True,
            "syncState": "IN_SYNC",
        }
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.request = AsyncMock(return_value=fake_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/api/agent/knowledge-status")

    assert response.status_code == 200
    body = response.json()
    assert body["sync"]["alignedWithCloud"] is True
    mock_client.request.assert_awaited()
    args, kwargs = mock_client.request.await_args
    assert args[0] == "GET"
    assert args[1].endswith("/admin/knowledge-status")
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_agent_knowledge_sync_bff_requires_sync_write() -> None:
    app = FastAPI()
    settings = SimpleNamespace(agent_api_url="http://agent.example", service_token="")

    def require_capability(_actor: object, capability: str) -> None:
        if capability == "ops.sync.write":
            raise HTTPException(status_code=403, detail="Forbidden.")

    register_agent_knowledge_sync_routes(
        app,
        resolved_settings=settings,
        current_actor=lambda: SimpleNamespace(role="VIEWER"),
        require_capability=require_capability,
    )
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post("/api/agent/knowledge-sync")
    assert response.status_code == 403
