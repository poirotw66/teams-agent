from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent_service.knowledge_release_control import read_firestore_release_reference
from agent_service.routers.health import _require_active_release_alignment
from agent_service.settings import RagSettings


class FakeSnapshot:
    def __init__(self, payload: dict[str, object] | None) -> None:
        self._payload = payload
        self.exists = payload is not None

    def to_dict(self) -> dict[str, object] | None:
        return self._payload


class FakeDocument:
    def __init__(self, payload: dict[str, object] | None) -> None:
        self._payload = payload

    def get(self) -> FakeSnapshot:
        return FakeSnapshot(self._payload)


class FakeCollection:
    def __init__(self, documents: dict[str, dict[str, object]]) -> None:
        self._documents = documents

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self._documents.get(document_id))


class FakeFirestoreClient:
    def __init__(self, collections: dict[str, dict[str, dict[str, object]]]) -> None:
        self._collections = collections

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self._collections.get(name, {}))


def _settings(tmp_path: Path) -> RagSettings:
    return RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_gcs_bucket="fallback-bucket",
    )


def test_control_plane_returns_pinned_active_release(tmp_path: Path) -> None:
    client = FakeFirestoreClient(
        {
            "knowledge_portal_config": {"active_release": {"release_id": "release-1"}},
            "knowledge_releases": {
                "release-1": {
                    "status": "ACTIVE",
                    "purpose": "PRODUCTION",
                    "tenant_id": "tenant-a",
                    "artifact_bucket": "release-bucket",
                    "manifest_generation": 11,
                    "index_generation": 12,
                    "index_sha256": "abc123",
                    "chunk_count": 39,
                    "vector_count": 39,
                    "embedding_model": "gemini-embedding-2",
                    "embedding_dimensions": 3072,
                }
            },
        }
    )

    reference = read_firestore_release_reference(
        _settings(tmp_path),
        client=client,
    )

    assert reference.release_id == "release-1"
    assert reference.purpose == "PRODUCTION"
    assert reference.tenant_id == "tenant-a"
    assert reference.bucket == "release-bucket"
    assert reference.manifest_generation == 11
    assert reference.index_generation == 12
    assert reference.index_sha256 == "abc123"
    assert reference.chunk_count == 39


def test_control_plane_rejects_failed_release(tmp_path: Path) -> None:
    client = FakeFirestoreClient(
        {
            "knowledge_releases": {
                "release-1": {
                    "status": "FAILED",
                    "artifact_bucket": "release-bucket",
                }
            }
        }
    )

    with pytest.raises(ValueError, match="unsafe status"):
        read_firestore_release_reference(
            _settings(tmp_path),
            release_id="release-1",
            client=client,
        )


def test_production_control_plane_rejects_e2e_release(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    object.__setattr__(settings, "deployment_environment", "prod")
    client = FakeFirestoreClient(
        {
            "knowledge_releases": {
                "release-e2e": {
                    "status": "ACTIVE",
                    "purpose": "E2E",
                    "artifact_bucket": "release-bucket",
                    "manifest_generation": 11,
                    "index_generation": 12,
                    "index_sha256": "abc123",
                }
            }
        }
    )

    with pytest.raises(ValueError, match="Production cannot load E2E"):
        read_firestore_release_reference(
            settings,
            release_id="release-e2e",
            client=client,
        )


@pytest.mark.asyncio
async def test_readiness_rejects_release_that_is_not_active(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    object.__setattr__(settings, "knowledge_release_store_mode", "GCS")
    object.__setattr__(settings, "knowledge_release_require_manifest", True)
    control = SimpleNamespace(
        read_active_release_id=lambda: "release-active",
    )
    state = SimpleNamespace(
        knowledge_release_id="release-stale",
        knowledge_index_artifact=object(),
        knowledge_release_control=control,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    with pytest.raises(HTTPException) as raised:
        await _require_active_release_alignment(request, settings)

    assert raised.value.status_code == 503
