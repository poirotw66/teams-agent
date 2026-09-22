"""Tests for FOLLOW_CLOUD hot-reload and Agent knowledge status contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from agent_service.deps_sync import apply_follow_cloud_mirror_reload
from agent_service.knowledge_release_cache import (
    VERIFIED_MARKER_FILENAME,
    tenant_release_cache_dir,
)
from agent_service.knowledge_release_sync import (
    KnowledgeReleaseSelectionMode,
    KnowledgeReleaseSyncer,
    KnowledgeSyncState,
)
from agent_service.release_artifacts import inspect_index_artifact
from agent_service.routers.knowledge_admin import _build_knowledge_status
from agent_service.settings import RagSettings
from knowledge_portal.models import ReleaseManifestEntry
from knowledge_portal.service_catalog_artifact import write_service_catalog_artifact


def _write_mirror(
    cache_dir: Path,
    *,
    tenant_id: str,
    release_id: str,
) -> Path:
    releases_root = tenant_release_cache_dir(cache_dir, tenant_id, release_id).parent
    release_dir = releases_root / release_id
    release_dir.mkdir(parents=True, exist_ok=True)
    (release_dir / "sources").mkdir(parents=True, exist_ok=True)
    (release_dir / "sources" / "doc-a.md").write_text("# A\n", encoding="utf-8")
    index_path = release_dir / "index" / "chunks.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "embeddingModel": "model-a",
                "chunks": [
                    {
                        "chunk_id": "1",
                        "source_path": "sources/doc-a.md",
                        "document_id": "doc-a",
                        "version_id": "v1",
                        "allowed_groups": ["grp_public"],
                        "vector": [0.1, 0.2],
                        "content": "content",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifact = inspect_index_artifact(index_path)
    (release_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseId": release_id,
                "purpose": "PRODUCTION",
                "tenantId": tenant_id,
                "documents": [
                    {
                        "document_id": "doc-a",
                        "version_id": "v1",
                        "title": "Doc A",
                        "content_hash": "hash-a",
                        "source_path": "sources/doc-a.md",
                        "acl_groups": ["grp_public"],
                    }
                ],
                "index": artifact.to_manifest_dict(),
                "runtimeArtifacts": [
                    {
                        "path": "index/chunks.json",
                        "generation": 1,
                        "sizeBytes": artifact.byte_size,
                        "sha256": artifact.sha256,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (release_dir / VERIFIED_MARKER_FILENAME).write_text(
        json.dumps(
            {
                "releaseId": release_id,
                "runtimeInventoryComplete": True,
                "verificationHash": artifact.sha256,
            }
        ),
        encoding="utf-8",
    )
    return index_path


def test_follow_cloud_reload_swaps_loaded_release(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    tenant_id = "tenant-a"
    release_id = "release-new"
    index_path = _write_mirror(cache_dir, tenant_id=tenant_id, release_id=release_id)
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_cache_dir=cache_dir,
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_selection_mode="FOLLOW_CLOUD",
        knowledge_release_require_vectors=True,
    )
    app = FastAPI()
    syncer = KnowledgeReleaseSyncer(settings)
    syncer.set_loaded_release_id("release-old")
    app.state.knowledge_release_syncer = syncer
    app.state.knowledge_release_id = "release-old"
    app.state.hybrid_settings = settings
    app.state.rag_model = None
    app.state.knowledge_router = MagicMock()
    fake_index = MagicMock()
    fake_index.chunks = []

    with (
        patch(
            "agent_service.deps_sync.load_validated_release_index",
            return_value=(fake_index, inspect_index_artifact(index_path)),
        ),
        patch("agent_service.deps_sync.RagAgent", return_value=MagicMock()),
        patch("agent_service.deps_sync.build_knowledge_service", return_value=MagicMock()),
        patch("agent_service.deps_sync.configure_service_scope_from_release", return_value=0),
    ):
        swapped = apply_follow_cloud_mirror_reload(
            app,
            settings,
            release_id=release_id,
        )

    assert swapped is True
    assert app.state.knowledge_release_id == release_id
    assert syncer.status.loaded_release_id == release_id


def test_pinned_selection_refuses_follow_cloud_reload(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_selection_mode="PINNED",
        knowledge_active_release_id="release-pin",
    )
    app = FastAPI()
    app.state.knowledge_release_id = "release-pin"
    assert (
        apply_follow_cloud_mirror_reload(app, settings, release_id="release-other")
        is False
    )
    assert app.state.knowledge_release_id == "release-pin"


def test_local_sandbox_selection_refuses_follow_cloud_reload(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_selection_mode="LOCAL_SANDBOX",
        knowledge_active_release_id="sandbox-1",
    )
    app = FastAPI()
    app.state.knowledge_release_id = "sandbox-1"
    assert (
        apply_follow_cloud_mirror_reload(app, settings, release_id="release-cloud")
        is False
    )
    assert app.state.knowledge_release_id == "sandbox-1"


@pytest.mark.asyncio
async def test_knowledge_status_aligned_only_when_all_match(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
    )
    syncer = KnowledgeReleaseSyncer(settings)
    with syncer._lock:
        syncer._status.cloud_active_release_id = "release-1"
        syncer._status.mirrored_release_id = "release-1"
        syncer._status.loaded_release_id = "release-stale"
        syncer._status.sync_state = KnowledgeSyncState.IN_SYNC
        syncer._status.runtime_inventory_complete = True
        syncer._status.behind_cloud = False
        syncer._status.selection_mode = KnowledgeReleaseSelectionMode.FOLLOW_CLOUD

    index = MagicMock()
    index.chunks = [1, 2]
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                knowledge_release_syncer=syncer,
                knowledge_release_id="release-1",
                knowledge_index_source="gcs_mirror",
                knowledge_index_path=tmp_path / "index.json",
                index=index,
            )
        )
    )
    payload = await _build_knowledge_status(request, settings)
    sync = payload["sync"]
    assert isinstance(sync, dict)
    assert sync["cloudActiveReleaseId"] == "release-1"
    assert sync["mirroredReleaseId"] == "release-1"
    assert sync["loadedReleaseId"] == "release-1"
    assert sync["alignedWithCloud"] is True

    request.app.state.knowledge_release_id = "release-stale"
    payload = await _build_knowledge_status(request, settings)
    sync = payload["sync"]
    assert isinstance(sync, dict)
    assert sync["loadedReleaseId"] == "release-stale"
    assert sync["alignedWithCloud"] is False


@pytest.mark.asyncio
async def test_knowledge_status_not_aligned_without_runtime_inventory(
    tmp_path: Path,
) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
    )
    syncer = KnowledgeReleaseSyncer(settings)
    with syncer._lock:
        syncer._status.cloud_active_release_id = "release-1"
        syncer._status.mirrored_release_id = "release-1"
        syncer._status.loaded_release_id = "release-1"
        syncer._status.sync_state = KnowledgeSyncState.IN_SYNC
        syncer._status.runtime_inventory_complete = False
        syncer._status.behind_cloud = False
        syncer._status.selection_mode = KnowledgeReleaseSelectionMode.FOLLOW_CLOUD

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                knowledge_release_syncer=syncer,
                knowledge_release_id="release-1",
                knowledge_index_source="gcs_mirror_index_only",
                knowledge_index_path=tmp_path / "index.json",
                index=MagicMock(chunks=[1]),
            )
        )
    )
    payload = await _build_knowledge_status(request, settings)
    sync = payload["sync"]
    assert isinstance(sync, dict)
    assert sync["alignedWithCloud"] is False
    assert sync["qaSnapshotComplete"] is False


def test_service_catalog_artifact_written_for_inventory(tmp_path: Path) -> None:
    release_dir = tmp_path / "release-1"
    release_dir.mkdir()
    path = write_service_catalog_artifact(
        release_dir,
        release_id="release-1",
        tenant_id="tenant-a",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-seat",
                version_id="v1",
                title="座位搬遷",
                content_hash="hash",
                source_path="sources/doc-seat.md",
                acl_groups=["grp_public"],
                source_aliases=["座位遷移", "搬位子"],
            )
        ],
    )
    assert path.as_posix().endswith("catalog/service_catalog.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["services"][0]["aliases"] == ["座位遷移", "搬位子"]
