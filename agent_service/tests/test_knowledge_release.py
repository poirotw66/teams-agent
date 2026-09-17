from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_service.deps import sync_knowledge_to_active_pointer
from agent_service.knowledge_release import (
    read_active_release_id,
    release_index_path,
    resolve_knowledge_index,
    write_active_release_pointer,
)
from agent_service.knowledge_release_control import KnowledgeReleaseReference
from agent_service.release_artifacts import (
    KnowledgeReleaseValidationError,
    inspect_index_artifact,
)
from agent_service.settings import RagSettings


def test_explicit_release_pin_ignores_mutable_active_pointer(tmp_path: Path) -> None:
    settings = replace(
        _settings(tmp_path),
        knowledge_active_release_id="release-pinned",
    )
    write_active_release_pointer(tmp_path / "releases", "release-other")

    app = SimpleNamespace(state=SimpleNamespace())

    assert sync_knowledge_to_active_pointer(app, settings) is False


def _settings(
    tmp_path: Path,
    *,
    mode: str = "AUTO",
    active_release_id: str | None = None,
    bundled_exists: bool = True,
    require_manifest: bool = False,
    require_vectors: bool = False,
) -> RagSettings:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    bundled = data_dir / "index" / "chunks.json"
    if bundled_exists:
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text('{"version":1,"embeddingModel":null,"chunks":[]}', encoding="utf-8")
    return RagSettings(
        data_dir=data_dir,
        index_path=bundled,
        auto_build_index=False,
        knowledge_release_mode=mode,
        knowledge_release_dir=tmp_path / "releases",
        knowledge_active_release_id=active_release_id,
        knowledge_release_require_manifest=require_manifest,
        knowledge_release_require_vectors=require_vectors,
    )


def test_resolve_knowledge_index_prefers_portal_release(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    release_id = "release-demo"
    index_path = release_index_path(settings.knowledge_release_dir, release_id)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        '{"version":1,"embeddingModel":null,"chunks":[{"chunk_id":"1"}]}', encoding="utf-8"
    )
    write_active_release_pointer(settings.knowledge_release_dir, release_id)

    resolved = resolve_knowledge_index(settings)
    assert resolved.release_id == release_id
    assert resolved.source == "portal_release"
    assert resolved.index_path == index_path


def test_resolve_allows_legacy_manifest_when_validation_is_optional(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings(tmp_path)
    release_id = "release-legacy"
    index_path = release_index_path(settings.knowledge_release_dir, release_id)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        '{"version":1,"embeddingModel":null,"chunks":[{"chunk_id":"1"}]}',
        encoding="utf-8",
    )
    manifest_path = index_path.parents[1] / "manifest.json"
    manifest_path.write_text(
        json.dumps({"releaseId": release_id, "indexArtifact": str(index_path)}),
        encoding="utf-8",
    )
    write_active_release_pointer(settings.knowledge_release_dir, release_id)

    resolved = resolve_knowledge_index(settings)

    assert resolved.index_path == index_path
    assert resolved.artifact is None
    assert "without optional manifest validation" in caplog.text


def test_resolve_rejects_legacy_manifest_when_validation_is_required(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, require_manifest=True)
    release_id = "release-legacy"
    index_path = release_index_path(settings.knowledge_release_dir, release_id)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        '{"version":1,"embeddingModel":null,"chunks":[{"chunk_id":"1"}]}',
        encoding="utf-8",
    )
    (index_path.parents[1] / "manifest.json").write_text(
        json.dumps({"releaseId": release_id, "indexArtifact": str(index_path)}),
        encoding="utf-8",
    )
    write_active_release_pointer(settings.knowledge_release_dir, release_id)

    with pytest.raises(
        KnowledgeReleaseValidationError,
        match="missing index metadata",
    ):
        resolve_knowledge_index(settings)


def test_resolve_knowledge_index_falls_back_to_bundled_in_auto_mode(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    resolved = resolve_knowledge_index(settings)
    assert resolved.source == "bundled_index"
    assert resolved.release_id is None


def test_portal_mode_requires_active_release(tmp_path: Path) -> None:
    settings = _settings(tmp_path, mode="PORTAL", bundled_exists=False)
    with pytest.raises(FileNotFoundError):
        resolve_knowledge_index(settings)


def test_active_release_pointer_round_trip(tmp_path: Path) -> None:
    release_dir = tmp_path / "releases"
    write_active_release_pointer(release_dir, "release-123")
    assert read_active_release_id(release_dir) == "release-123"
    payload = json.loads((release_dir / "active_release.json").read_text(encoding="utf-8"))
    assert payload["releaseId"] == "release-123"


def test_resolve_validates_release_manifest_and_vector_metadata(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        mode="PORTAL",
        active_release_id="release-valid",
        bundled_exists=False,
        require_manifest=True,
        require_vectors=True,
    )
    index_path = _write_release(
        settings.knowledge_release_dir,
        "release-valid",
        vectors=[[0.1, 0.2], [0.3, 0.4]],
    )

    resolved = resolve_knowledge_index(settings)

    assert resolved.index_path == index_path
    assert resolved.artifact is not None
    assert resolved.artifact.chunk_count == 2
    assert resolved.artifact.vector_count == 2
    assert resolved.artifact.embedding_dimensions == 2


def test_resolve_rejects_index_changed_after_manifest_creation(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        mode="PORTAL",
        active_release_id="release-tampered",
        bundled_exists=False,
        require_manifest=True,
    )
    index_path = _write_release(
        settings.knowledge_release_dir,
        "release-tampered",
        vectors=[[0.1, 0.2]],
    )
    index_path.write_text(
        '{"version":1,"embeddingModel":"model-a","chunks":[]}',
        encoding="utf-8",
    )

    with pytest.raises(
        KnowledgeReleaseValidationError,
        match="metadata mismatch",
    ):
        resolve_knowledge_index(settings)


def test_resolve_rejects_vectorless_production_release(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        mode="PORTAL",
        active_release_id="release-sparse",
        bundled_exists=False,
        require_manifest=True,
        require_vectors=True,
    )
    _write_release(settings.knowledge_release_dir, "release-sparse", vectors=[None])

    with pytest.raises(
        KnowledgeReleaseValidationError,
        match="embedding for every chunk",
    ):
        resolve_knowledge_index(settings)


def test_resolve_rejects_chunk_acl_that_differs_from_manifest(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        mode="PORTAL",
        active_release_id="release-acl-mismatch",
        bundled_exists=False,
        require_manifest=True,
        require_vectors=True,
    )
    index_path = _write_release(
        settings.knowledge_release_dir,
        "release-acl-mismatch",
        vectors=[[0.1, 0.2]],
    )
    manifest_path = index_path.parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["documents"][0]["acl_groups"] = ["restricted-group"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        KnowledgeReleaseValidationError,
        match="chunk ACL does not match",
    ):
        resolve_knowledge_index(settings)


def test_resolve_accepts_explicit_public_chunk_acl(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        mode="PORTAL",
        active_release_id="release-explicit-public",
        bundled_exists=False,
        require_manifest=True,
        require_vectors=True,
    )
    index_path = _write_release(
        settings.knowledge_release_dir,
        "release-explicit-public",
        vectors=[[0.1, 0.2]],
    )
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["chunks"][0]["allowed_groups"] = ["grp_public"]
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    artifact = inspect_index_artifact(index_path)
    manifest_path = index_path.parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["index"] = artifact.to_manifest_dict()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert resolve_knowledge_index(settings).release_id == "release-explicit-public"


def test_resolve_rejects_chunk_identity_that_differs_from_manifest(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        mode="PORTAL",
        active_release_id="release-identity-mismatch",
        bundled_exists=False,
        require_manifest=True,
        require_vectors=True,
    )
    index_path = _write_release(
        settings.knowledge_release_dir,
        "release-identity-mismatch",
        vectors=[[0.1, 0.2]],
    )
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["chunks"][0]["version_id"] = "wrong-version"
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    artifact = inspect_index_artifact(index_path)
    manifest_path = index_path.parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["index"] = artifact.to_manifest_dict()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        KnowledgeReleaseValidationError,
        match="version_id does not match",
    ):
        resolve_knowledge_index(settings)


def test_resolve_rejects_alias_shared_by_canonical_documents(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        mode="PORTAL",
        active_release_id="release-alias-collision",
        bundled_exists=False,
        require_manifest=True,
        require_vectors=True,
    )
    index_path = _write_release(
        settings.knowledge_release_dir,
        "release-alias-collision",
        vectors=[[0.1, 0.2], [0.3, 0.4]],
    )
    manifest_path = index_path.parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["documents"][0]["source_aliases"] = ["VPN FAQ"]
    manifest["documents"][1]["source_aliases"] = [" vpn faq "]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        KnowledgeReleaseValidationError,
        match="identifies multiple canonical documents",
    ):
        resolve_knowledge_index(settings)


def test_gcs_resolver_matches_firestore_metadata_to_downloaded_release(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    index_path = _write_release(
        cache_dir,
        "release-gcs",
        vectors=[[0.1, 0.2]],
        tenant_id="tenant-a",
    )
    artifact = inspect_index_artifact(index_path)
    reference = KnowledgeReleaseReference(
        release_id="release-gcs",
        purpose="PRODUCTION",
        tenant_id="tenant-a",
        bucket="knowledge-bucket",
        manifest_generation=10,
        index_generation=11,
        index_sha256=artifact.sha256,
        chunk_count=artifact.chunk_count,
        vector_count=artifact.vector_count,
        embedding_model=artifact.embedding_model,
        embedding_dimensions=artifact.embedding_dimensions,
    )
    settings = _settings(
        tmp_path,
        mode="PORTAL",
        bundled_exists=False,
        require_manifest=True,
        require_vectors=True,
    )
    object.__setattr__(settings, "knowledge_release_store_mode", "GCS")
    object.__setattr__(settings, "knowledge_release_gcs_bucket", reference.bucket)
    object.__setattr__(settings, "knowledge_release_cache_dir", cache_dir)

    with (
        patch(
            "agent_service.knowledge_release.read_firestore_release_reference",
            return_value=reference,
        ),
        patch(
            "agent_service.knowledge_release.download_release_metadata",
            return_value=index_path,
        ),
    ):
        resolved = resolve_knowledge_index(settings)

    assert resolved.source == "gcs_release"
    assert resolved.release_id == "release-gcs"
    assert resolved.artifact == artifact
    assert resolved.release_dir == cache_dir


def _write_release(
    release_dir: Path,
    release_id: str,
    *,
    vectors: list[list[float] | None],
    tenant_id: str | None = None,
) -> Path:
    index_path = release_index_path(release_dir, release_id)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    chunks = [
        {
            "chunk_id": f"chunk-{index}",
            "title": f"Title {index}",
            "source_path": f"sources/doc-{index}.md",
            "content": f"Content {index}",
            "allowed_groups": [],
            "vector": vector,
            "document_id": f"doc-{index}",
            "version_id": f"version-{index}",
            "release_id": release_id,
        }
        for index, vector in enumerate(vectors)
    ]
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "embeddingModel": "model-a" if any(vectors) else None,
                "chunks": chunks,
            }
        ),
        encoding="utf-8",
    )
    artifact = inspect_index_artifact(index_path)
    manifest_path = index_path.parents[1] / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseId": release_id,
                "purpose": "PRODUCTION",
                **({"tenantId": tenant_id} if tenant_id else {}),
                "documents": [
                    {
                        "document_id": f"doc-{index}",
                        "version_id": f"version-{index}",
                        "title": f"Title {index}",
                        "content_hash": f"hash-{index}",
                        "source_path": f"sources/doc-{index}.md",
                        "acl_groups": ["grp_public"],
                    }
                    for index, _vector in enumerate(vectors)
                ],
                "index": artifact.to_manifest_dict(),
            }
        ),
        encoding="utf-8",
    )
    return index_path
