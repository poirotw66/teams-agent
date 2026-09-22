"""Regression: GCS Agent reload must sync the cloud-active mirror first."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from agent_service.contracts import ReloadKnowledgeRequest
from agent_service.knowledge_release_sync import KnowledgeSyncState
from agent_service.routers import knowledge_admin_reload as reload_mod
from agent_service.settings import RagSettings


@dataclass
class _FakeSyncStatus:
    cloud_active_release_id: str = "release-new"
    mirrored_release_id: str = "release-new"
    sync_state: KnowledgeSyncState = KnowledgeSyncState.IN_SYNC


class _FakeSyncer:
    def __init__(self) -> None:
        self.calls = 0
        self.loaded: str | None = None

    def sync_now(self) -> _FakeSyncStatus:
        self.calls += 1
        return _FakeSyncStatus()

    def set_loaded_release_id(self, release_id: str | None) -> None:
        self.loaded = release_id


@pytest.mark.asyncio
async def test_gcs_reload_syncs_mirror_before_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = RagSettings(
        data_dir=tmp_path / "data",
        index_path=tmp_path / "data" / "index" / "chunks.json",
        auto_build_index=False,
        knowledge_release_store_mode="GCS",
        knowledge_release_cache_dir=tmp_path / "cache",
        knowledge_release_tenant_id="default",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
        model=None,
        agent_model=None,
        embedding_model=None,
        service_token="secret",
    )
    app = FastAPI()
    syncer = _FakeSyncer()
    app.state.knowledge_release_syncer = syncer
    app.state.rag_model = None
    app.state.hybrid_settings = settings
    app.state.knowledge_router = MagicMock()
    request = SimpleNamespace(app=app)

    index_path = tmp_path / "cache" / "tenants" / "default" / "releases" / "release-new" / "index" / "chunks.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        '{"version":1,"chunks":[{"chunk_id":"c1","source_path":"sources/a.md","title":"A","content":"x"}]}',
        encoding="utf-8",
    )

    resolved = SimpleNamespace(
        release_id="release-new",
        index_path=index_path,
        source="gcs_mirror",
        artifact=None,
        file_search_store=None,
        release_dir=index_path.parents[1].parent,
    )
    monkeypatch.setattr(reload_mod, "resolve_knowledge_index", lambda *_a, **_k: resolved)
    monkeypatch.setattr(reload_mod, "read_active_release_id", lambda *_a, **_k: "release-new")
    monkeypatch.setattr(
        reload_mod.HybridIndex,
        "load",
        classmethod(lambda cls, *_a, **_k: SimpleNamespace(chunks=[SimpleNamespace()])),
    )
    monkeypatch.setattr(reload_mod, "hydrate_index_sources", lambda *_a, **_k: None)
    monkeypatch.setattr(reload_mod, "RagAgent", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(reload_mod, "build_knowledge_service", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(reload_mod, "embedding_model_for_load", lambda *_a, **_k: None)
    monkeypatch.setattr(reload_mod, "hybrid_index_fusion_kwargs", lambda *_a, **_k: {})
    monkeypatch.setattr(reload_mod, "configure_service_scope_from_release", lambda *_a, **_k: None)

    result = await reload_mod.perform_knowledge_reload(
        request,  # type: ignore[arg-type]
        resolved_settings=settings,
        payload=ReloadKnowledgeRequest.model_validate({"releaseId": "release-new"}),
    )

    assert syncer.calls == 1
    assert result["releaseId"] == "release-new"
    assert result["status"] == "reloaded"
