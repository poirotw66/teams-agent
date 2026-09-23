"""Tests for knowledge release inventory, cache paths, and GCS syncer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_service.knowledge_release_cache import (
    legacy_release_cache_dir,
    resolve_mirrored_release_dir,
    tenant_release_cache_dir,
)
from agent_service.knowledge_release_gcs import (
    download_inventory_artifacts,
    publish_release_directory,
)
from agent_service.knowledge_release_sync import (
    KnowledgeReleaseSelectionMode,
    KnowledgeReleaseSyncer,
    KnowledgeSyncState,
    is_verified_qa_snapshot,
    resolve_selection_mode,
)
from agent_service.release_artifacts import inspect_index_artifact
from agent_service.settings import RagSettings
from knowledge_core.runtime_inventory import (
    build_runtime_artifact_inventory,
    is_qa_sync_relative_path,
    parse_runtime_artifact_inventory,
)
from knowledge_portal.service_catalog_artifact import write_service_catalog_artifact


class FakeBlob:
    def __init__(
        self,
        objects: dict[tuple[str, int], bytes],
        latest_generations: dict[str, int],
        name: str,
        generation: int | None = None,
    ) -> None:
        self._objects = objects
        self._latest_generations = latest_generations
        self.name = name
        self.generation = generation
        self.metadata: dict[str, str] = {}

    def upload_from_filename(
        self,
        filename: str,
        *,
        if_generation_match: int,
    ) -> None:
        assert if_generation_match == 0
        if self.name in self._latest_generations:
            raise RuntimeError("precondition failed")
        self.generation = len(self._objects) + 1
        self._objects[(self.name, self.generation)] = Path(filename).read_bytes()
        self._latest_generations[self.name] = self.generation

    def download_to_filename(self, filename: str) -> None:
        generation = self.generation or self._latest_generations[self.name]
        Path(filename).write_bytes(self._objects[(self.name, generation)])


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, int], bytes] = {}
        self.latest_generations: dict[str, int] = {}

    def blob(self, name: str, generation: int | None = None) -> FakeBlob:
        return FakeBlob(self.objects, self.latest_generations, name, generation)


class FakeStorageClient:
    def __init__(self) -> None:
        self.bucket_instance = FakeBucket()

    def bucket(self, _name: str) -> FakeBucket:
        return self.bucket_instance


def _write_minimal_release(release_dir: Path, release_id: str, tenant_id: str) -> Path:
    release_dir.mkdir(parents=True, exist_ok=True)
    sources = release_dir / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "doc-a.md").write_text("# Doc A\ncontent", encoding="utf-8")
    (release_dir / "original").mkdir(parents=True, exist_ok=True)
    (release_dir / "original" / "doc-a.pdf").write_bytes(b"%PDF-fake")
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
            }
        ),
        encoding="utf-8",
    )
    return index_path


def _sync_state(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def test_explicit_follow_cloud_wins_over_active_release_id(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_active_release_id="release-pin",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
    )
    assert resolve_selection_mode(settings) is KnowledgeReleaseSelectionMode.FOLLOW_CLOUD


def test_qa_sync_path_filters_exclude_original_and_file_search() -> None:
    assert is_qa_sync_relative_path("index/chunks.json")
    assert is_qa_sync_relative_path("sources/doc.md")
    assert is_qa_sync_relative_path("assets/slug/p01.png")
    assert not is_qa_sync_relative_path("original/doc.pdf")
    assert not is_qa_sync_relative_path("file-search/chunk.md")
    assert not is_qa_sync_relative_path("manifest.json")


def test_build_inventory_skips_original_objects(tmp_path: Path) -> None:
    release_dir = tmp_path / "release-1"
    _write_minimal_release(release_dir, "release-1", "tenant-a")
    generations = {
        "index/chunks.json": 10,
        "sources/doc-a.md": 11,
        "original/doc-a.pdf": 12,
    }
    inventory = build_runtime_artifact_inventory(
        generations=generations,
        release_dir=release_dir,
    )
    paths = {entry.relative_path for entry in inventory}
    assert paths == {"index/chunks.json", "sources/doc-a.md"}


def test_legacy_manifest_without_inventory_is_not_full_qa_snapshot() -> None:
    assert parse_runtime_artifact_inventory({"releaseId": "r1"}) is None


def test_tenant_scoped_cache_paths(tmp_path: Path) -> None:
    scoped = tenant_release_cache_dir(tmp_path, "tenant-a", "release-1")
    assert scoped == tmp_path / "tenants" / "tenant-a" / "releases" / "release-1"
    legacy = legacy_release_cache_dir(tmp_path, "release-1")
    legacy.mkdir(parents=True)
    (legacy / "manifest.json").write_text("{}", encoding="utf-8")
    assert (
        resolve_mirrored_release_dir(tmp_path, tenant_id="tenant-a", release_id="release-1")
        == legacy
    )


def test_publish_embeds_runtime_artifacts_inventory(tmp_path: Path) -> None:
    release_id = "release-inv"
    release_dir = tmp_path / "source" / release_id
    _write_minimal_release(release_dir, release_id, "tenant-a")
    client = FakeStorageClient()

    published = publish_release_directory(
        release_dir,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id="tenant-a",
        release_id=release_id,
        client=client,
    )

    assert published.runtime_artifacts
    manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    inventory = parse_runtime_artifact_inventory(manifest)
    assert inventory is not None
    assert {entry.relative_path for entry in inventory} == {
        "index/chunks.json",
        "sources/doc-a.md",
    }
    assert "original/doc-a.pdf" not in {entry.relative_path for entry in inventory}


def test_download_inventory_verifies_size_and_hash(tmp_path: Path) -> None:
    release_id = "release-inv"
    release_dir = tmp_path / "source" / release_id
    _write_minimal_release(release_dir, release_id, "tenant-a")
    client = FakeStorageClient()
    published = publish_release_directory(
        release_dir,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id="tenant-a",
        release_id=release_id,
        client=client,
    )
    destination = tmp_path / "dest"
    destination.mkdir()
    download_inventory_artifacts(
        destination,
        bucket_name=published.bucket,
        object_prefix="knowledge-releases",
        tenant_id="tenant-a",
        release_id=release_id,
        inventory=list(published.runtime_artifacts),
        client=client,
    )
    assert (destination / "sources" / "doc-a.md").is_file()
    assert not (destination / "original" / "doc-a.pdf").exists()


def test_publish_includes_service_catalog_in_runtime_inventory(tmp_path: Path) -> None:
    release_id = "release-catalog"
    release_dir = tmp_path / "source" / release_id
    _write_minimal_release(release_dir, release_id, "tenant-a")
    write_service_catalog_artifact(
        release_dir,
        release_id=release_id,
        tenant_id="tenant-a",
        manifest=[],
    )
    client = FakeStorageClient()
    published = publish_release_directory(
        release_dir,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id="tenant-a",
        release_id=release_id,
        client=client,
    )
    paths = {entry.relative_path for entry in published.runtime_artifacts}
    assert "catalog/service_catalog.json" in paths
    assert "original/doc-a.pdf" not in paths
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
    )
    assert resolve_selection_mode(settings) is KnowledgeReleaseSelectionMode.FOLLOW_CLOUD
    object.__setattr__(settings, "knowledge_active_release_id", "release-pin")
    assert resolve_selection_mode(settings) is KnowledgeReleaseSelectionMode.PINNED
    object.__setattr__(settings, "knowledge_release_selection_mode", "FOLLOW_CLOUD")
    assert resolve_selection_mode(settings) is KnowledgeReleaseSelectionMode.FOLLOW_CLOUD
    object.__setattr__(settings, "knowledge_release_selection_mode", "LOCAL_SANDBOX")
    assert resolve_selection_mode(settings) is KnowledgeReleaseSelectionMode.LOCAL_SANDBOX


def test_syncer_downloads_inventory_and_promotes_tenant_mirror(tmp_path: Path) -> None:
    release_id = "release-sync"
    tenant_id = "tenant-a"
    source = tmp_path / "source" / release_id
    index_path = _write_minimal_release(source, release_id, tenant_id)
    artifact = inspect_index_artifact(index_path)
    client = FakeStorageClient()
    published = publish_release_directory(
        source,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id=tenant_id,
        release_id=release_id,
        client=client,
    )

    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_gcs_prefix="knowledge-releases",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=tmp_path / "cache",
        knowledge_release_sync_interval_seconds=300,
        knowledge_release_require_vectors=True,
    )
    reference = type(
        "Ref",
        (),
        {
            "release_id": release_id,
            "purpose": "PRODUCTION",
            "tenant_id": tenant_id,
            "bucket": published.bucket,
            "manifest_generation": published.manifest_generation,
            "index_generation": published.index_generation,
            "index_sha256": artifact.sha256,
            "chunk_count": artifact.chunk_count,
            "vector_count": artifact.vector_count,
            "embedding_model": artifact.embedding_model,
            "embedding_dimensions": artifact.embedding_dimensions,
        },
    )()

    syncer = KnowledgeReleaseSyncer(settings, storage_client=client)
    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        return_value=reference,
    ):
        status = syncer.sync_now()

    mirrored = tenant_release_cache_dir(settings.knowledge_release_cache_dir, tenant_id, release_id)
    assert _sync_state(status.sync_state) == KnowledgeSyncState.IN_SYNC.value
    assert status.mirrored_release_id == release_id
    assert status.qa_snapshot_complete is True
    assert status.artifact_count >= 2
    assert is_verified_qa_snapshot(mirrored)
    assert (mirrored / "sources" / "doc-a.md").is_file()
    assert not (mirrored / "original").exists()


def test_syncer_marks_legacy_index_only_when_inventory_missing(
    tmp_path: Path,
) -> None:
    release_id = "release-legacy"
    tenant_id = "tenant-a"
    source = tmp_path / "source" / release_id
    index_path = _write_minimal_release(source, release_id, tenant_id)
    artifact = inspect_index_artifact(index_path)
    client = FakeStorageClient()
    bucket = client.bucket_instance
    prefix = f"knowledge-releases/tenants/{tenant_id}/releases/{release_id}"

    def _put(name: str, path: Path) -> int:
        generation = len(bucket.objects) + 1
        bucket.objects[(name, generation)] = path.read_bytes()
        bucket.latest_generations[name] = generation
        return generation

    index_generation = _put(f"{prefix}/index/chunks.json", index_path)
    _put(f"{prefix}/sources/doc-a.md", source / "sources" / "doc-a.md")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["storage"] = {
        "bucket": "knowledge",
        "objectPrefix": prefix,
        "indexGeneration": index_generation,
    }
    manifest_path = source / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_generation = _put(f"{prefix}/manifest.json", manifest_path)

    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_gcs_prefix="knowledge-releases",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=tmp_path / "cache",
        knowledge_release_require_vectors=True,
    )
    reference = type(
        "Ref",
        (),
        {
            "release_id": release_id,
            "purpose": "PRODUCTION",
            "tenant_id": tenant_id,
            "bucket": "knowledge",
            "manifest_generation": manifest_generation,
            "index_generation": index_generation,
            "index_sha256": artifact.sha256,
            "chunk_count": artifact.chunk_count,
            "vector_count": artifact.vector_count,
            "embedding_model": artifact.embedding_model,
            "embedding_dimensions": artifact.embedding_dimensions,
        },
    )()
    syncer = KnowledgeReleaseSyncer(settings, storage_client=client)
    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        return_value=reference,
    ):
        status = syncer.sync_now()

    assert _sync_state(status.sync_state) == KnowledgeSyncState.IN_SYNC.value
    assert status.qa_snapshot_complete is False
    assert status.runtime_inventory_complete is False


def test_sync_interval_must_be_positive(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_sync_interval_seconds=0,
    )
    with pytest.raises(ValueError, match="SYNC_INTERVAL"):
        settings.validate()


def _reference_for(
    *,
    release_id: str,
    tenant_id: str,
    published: object,
    artifact: object,
) -> object:
    return type(
        "Ref",
        (),
        {
            "release_id": release_id,
            "purpose": "PRODUCTION",
            "tenant_id": tenant_id,
            "bucket": getattr(published, "bucket", "knowledge"),
            "manifest_generation": published.manifest_generation,
            "index_generation": published.index_generation,
            "index_sha256": artifact.sha256,
            "chunk_count": artifact.chunk_count,
            "vector_count": artifact.vector_count,
            "embedding_model": artifact.embedding_model,
            "embedding_dimensions": artifact.embedding_dimensions,
        },
    )()


def test_download_rejects_hash_mismatch(tmp_path: Path) -> None:
    release_id = "release-hash"
    release_dir = tmp_path / "source" / release_id
    _write_minimal_release(release_dir, release_id, "tenant-a")
    client = FakeStorageClient()
    published = publish_release_directory(
        release_dir,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id="tenant-a",
        release_id=release_id,
        client=client,
    )
    # Corrupt a downloaded object while keeping inventory size metadata.
    target = next(
        entry for entry in published.runtime_artifacts if entry.relative_path == "sources/doc-a.md"
    )
    object_name = f"knowledge-releases/tenants/tenant-a/releases/{release_id}/sources/doc-a.md"
    original = client.bucket_instance.objects[(object_name, target.generation)]
    # Same length, different content → size check passes, hash fails.
    tampered = bytes((b ^ 0xFF) for b in original)
    assert len(tampered) == len(original)
    client.bucket_instance.objects[(object_name, target.generation)] = tampered
    destination = tmp_path / "dest"
    destination.mkdir()
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        download_inventory_artifacts(
            destination,
            bucket_name=published.bucket,
            object_prefix="knowledge-releases",
            tenant_id="tenant-a",
            release_id=release_id,
            inventory=list(published.runtime_artifacts),
            client=client,
        )


def test_download_rejects_size_mismatch(tmp_path: Path) -> None:
    from knowledge_core.runtime_inventory import RuntimeArtifactEntry

    release_id = "release-size"
    release_dir = tmp_path / "source" / release_id
    _write_minimal_release(release_dir, release_id, "tenant-a")
    client = FakeStorageClient()
    published = publish_release_directory(
        release_dir,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id="tenant-a",
        release_id=release_id,
        client=client,
    )
    entries = []
    for entry in published.runtime_artifacts:
        if entry.relative_path == "sources/doc-a.md":
            entries.append(
                RuntimeArtifactEntry(
                    relative_path=entry.relative_path,
                    generation=entry.generation,
                    size_bytes=entry.size_bytes + 99,
                    sha256=entry.sha256,
                )
            )
        else:
            entries.append(entry)
    destination = tmp_path / "dest"
    destination.mkdir()
    with pytest.raises(RuntimeError, match="size mismatch"):
        download_inventory_artifacts(
            destination,
            bucket_name=published.bucket,
            object_prefix="knowledge-releases",
            tenant_id="tenant-a",
            release_id=release_id,
            inventory=entries,
            client=client,
        )


def test_download_rejects_path_traversal_and_absolute_paths(tmp_path: Path) -> None:
    from knowledge_core.runtime_inventory import RuntimeArtifactEntry, safe_release_relative_path

    with pytest.raises(ValueError, match="Unsafe artifact path"):
        safe_release_relative_path("../secrets.txt")
    with pytest.raises(ValueError, match="Unsafe artifact path"):
        safe_release_relative_path("/etc/passwd")

    destination = tmp_path / "dest"
    destination.mkdir()
    client = FakeStorageClient()
    bad = RuntimeArtifactEntry(
        relative_path="../escape.md",
        generation=1,
        size_bytes=1,
        sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="Unsafe artifact path"):
        download_inventory_artifacts(
            destination,
            bucket_name="knowledge",
            object_prefix="knowledge-releases",
            tenant_id="tenant-a",
            release_id="r1",
            inventory=[bad],
            client=client,
        )


def test_gcs_mode_without_verified_snapshot_makes_knowledge_unavailable(
    tmp_path: Path,
) -> None:
    from agent_service.knowledge_release import resolve_knowledge_index

    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_tenant_id="tenant-a",
        knowledge_release_cache_dir=tmp_path / "cache",
        knowledge_release_require_vectors=True,
    )
    with pytest.raises(FileNotFoundError, match="No verified local knowledge snapshot"):
        resolve_knowledge_index(settings)


def test_pinned_loaded_release_not_overwritten_by_follow_sync(tmp_path: Path) -> None:
    tenant_id = "tenant-a"
    cloud_id = "release-cloud"
    pinned_id = "release-pinned"
    cache = tmp_path / "cache"
    client = FakeStorageClient()
    refs: dict[str, object] = {}
    for release_id in (cloud_id, pinned_id):
        source = tmp_path / "source" / release_id
        index_path = _write_minimal_release(source, release_id, tenant_id)
        artifact = inspect_index_artifact(index_path)
        published = publish_release_directory(
            source,
            bucket_name="knowledge",
            object_prefix="knowledge-releases",
            tenant_id=tenant_id,
            release_id=release_id,
            client=client,
        )
        refs[release_id] = _reference_for(
            release_id=release_id,
            tenant_id=tenant_id,
            published=published,
            artifact=artifact,
        )

    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_gcs_prefix="knowledge-releases",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=cache,
        knowledge_active_release_id=pinned_id,
        knowledge_release_selection_mode="PINNED",
        knowledge_release_require_vectors=True,
    )
    syncer = KnowledgeReleaseSyncer(
        settings,
        storage_client=client,
        loaded_release_id=pinned_id,
    )

    def _read_ref(_settings: object, *, release_id: str | None = None, client: object = None):
        del _settings, client
        key = release_id or cloud_id
        return refs[key]

    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        side_effect=_read_ref,
    ):
        status = syncer.sync_now()

    assert status.cloud_active_release_id == cloud_id
    assert status.mirrored_release_id == pinned_id
    assert status.loaded_release_id == pinned_id
    assert is_verified_qa_snapshot(tenant_release_cache_dir(cache, tenant_id, pinned_id))


def test_prune_keeps_last_two_verified_releases(tmp_path: Path) -> None:
    tenant_id = "tenant-a"
    cache = tmp_path / "cache"
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=cache,
    )
    syncer = KnowledgeReleaseSyncer(settings)
    releases_root = tenant_release_cache_dir(cache, tenant_id, "r0").parent
    releases_root.mkdir(parents=True, exist_ok=True)
    for name in ("old-a", "old-b", "old-c", "keep-active"):
        path = releases_root / name
        path.mkdir()
        (path / "manifest.json").write_text("{}", encoding="utf-8")
        (path / ".qa_snapshot_verified").write_text("{}", encoding="utf-8")
    # Distinct mtimes so prune ordering is deterministic.
    import os
    import time

    base = time.time() - 100
    for index, name in enumerate(("old-a", "old-b", "old-c", "keep-active")):
        os.utime(releases_root / name, (base + index, base + index))

    syncer._prune_old_mirrors(keep_ids={"keep-active"})
    remaining = sorted(child.name for child in releases_root.iterdir() if child.is_dir())
    # keep-active always retained; plus one more recent verified (old-c).
    assert "keep-active" in remaining
    assert "old-c" in remaining
    assert "old-a" not in remaining
    assert "old-b" not in remaining
    assert len(remaining) == 2


def test_concurrent_sync_uses_exclusive_file_lock(tmp_path: Path) -> None:
    import threading

    from agent_service.knowledge_release_sync import _FileLock

    lock_path = tmp_path / "sync.lock"
    held = threading.Event()
    released = threading.Event()
    second_entered = threading.Event()

    def _holder() -> None:
        with _FileLock(lock_path):
            held.set()
            assert released.wait(timeout=2.0)

    first = threading.Thread(target=_holder)
    first.start()
    assert held.wait(timeout=2.0)

    def _waiter() -> None:
        with _FileLock(lock_path):
            second_entered.set()

    second = threading.Thread(target=_waiter)
    second.start()
    # Second thread must block while first holds the lock.
    assert not second_entered.wait(timeout=0.2)
    released.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)
    assert second_entered.is_set()


def test_syncer_follow_cloud_reloads_loaded_after_full_qa_mirror(
    tmp_path: Path,
) -> None:
    release_id = "release-reload"
    tenant_id = "tenant-a"
    source = tmp_path / "source" / release_id
    index_path = _write_minimal_release(source, release_id, tenant_id)
    artifact = inspect_index_artifact(index_path)
    client = FakeStorageClient()
    published = publish_release_directory(
        source,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id=tenant_id,
        release_id=release_id,
        client=client,
    )
    reference = type(
        "Ref",
        (),
        {
            "release_id": release_id,
            "purpose": "PRODUCTION",
            "tenant_id": tenant_id,
            "bucket": published.bucket,
            "manifest_generation": published.manifest_generation,
            "index_generation": published.index_generation,
            "index_sha256": artifact.sha256,
            "chunk_count": artifact.chunk_count,
            "vector_count": artifact.vector_count,
            "embedding_model": artifact.embedding_model,
            "embedding_dimensions": artifact.embedding_dimensions,
        },
    )()
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_gcs_prefix="knowledge-releases",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=tmp_path / "cache",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
        knowledge_release_require_vectors=True,
    )
    reloads: list[str] = []
    syncer = KnowledgeReleaseSyncer(settings, storage_client=client)
    syncer.set_loaded_release_id("release-old")

    def _on_ready(ready_id: str, _mirror_dir: Path) -> None:
        reloads.append(ready_id)
        syncer.set_loaded_release_id(ready_id)

    syncer.set_follow_cloud_ready_handler(_on_ready)
    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        return_value=reference,
    ):
        status = syncer.sync_now()

    assert _sync_state(status.sync_state) == KnowledgeSyncState.IN_SYNC.value
    assert status.qa_snapshot_complete is True
    assert reloads == [release_id]
    assert syncer.status.loaded_release_id == release_id
    public = syncer.status.to_public_dict()
    assert public["loadedReleaseId"] == release_id
    assert public["alignedWithCloud"] is True


def test_pinned_and_local_sandbox_never_claim_cloud_alignment(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_selection_mode="PINNED",
        knowledge_active_release_id="release-pinned",
    )
    syncer = KnowledgeReleaseSyncer(settings, loaded_release_id="release-pinned")
    with syncer._lock:
        syncer._status.cloud_active_release_id = "release-pinned"
        syncer._status.mirrored_release_id = "release-pinned"
        syncer._status.loaded_release_id = "release-pinned"
        syncer._status.sync_state = KnowledgeSyncState.IN_SYNC
        syncer._status.runtime_inventory_complete = True
        syncer._status.behind_cloud = False
        syncer._status.selection_mode = KnowledgeReleaseSelectionMode.PINNED
    pinned_public = syncer.status.to_public_dict()
    assert pinned_public["selectionMode"] == "PINNED"
    assert pinned_public["alignedWithCloud"] is False
    assert pinned_public["matchesCloudProduction"] is False

    with syncer._lock:
        syncer._status.selection_mode = KnowledgeReleaseSelectionMode.LOCAL_SANDBOX
    sandbox_public = syncer.status.to_public_dict()
    assert sandbox_public["selectionMode"] == "LOCAL_SANDBOX"
    assert sandbox_public["alignedWithCloud"] is False
    assert sandbox_public["matchesCloudProduction"] is False


def test_syncer_hash_mismatch_marks_failed_not_aligned(tmp_path: Path) -> None:
    release_id = "release-bad-hash"
    tenant_id = "tenant-a"
    source = tmp_path / "source" / release_id
    index_path = _write_minimal_release(source, release_id, tenant_id)
    artifact = inspect_index_artifact(index_path)
    client = FakeStorageClient()
    published = publish_release_directory(
        source,
        bucket_name="knowledge",
        object_prefix="knowledge-releases",
        tenant_id=tenant_id,
        release_id=release_id,
        client=client,
    )
    # Corrupt a published object with same-size bytes so SHA-256 fails closed.
    corrupted_key = next(
        name for (name, _gen) in client.bucket_instance.objects if name.endswith("sources/doc-a.md")
    )
    gen = client.bucket_instance.latest_generations[corrupted_key]
    original = client.bucket_instance.objects[(corrupted_key, gen)]
    client.bucket_instance.objects[(corrupted_key, gen)] = (
        b"X" * len(original) if original else b"X"
    )

    reference = type(
        "Ref",
        (),
        {
            "release_id": release_id,
            "purpose": "PRODUCTION",
            "tenant_id": tenant_id,
            "bucket": published.bucket,
            "manifest_generation": published.manifest_generation,
            "index_generation": published.index_generation,
            "index_sha256": artifact.sha256,
            "chunk_count": artifact.chunk_count,
            "vector_count": artifact.vector_count,
            "embedding_model": artifact.embedding_model,
            "embedding_dimensions": artifact.embedding_dimensions,
        },
    )()
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_gcs_prefix="knowledge-releases",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=tmp_path / "cache",
        knowledge_release_require_vectors=True,
    )
    syncer = KnowledgeReleaseSyncer(settings, storage_client=client)
    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        return_value=reference,
    ):
        status = syncer.sync_now()

    assert _sync_state(status.sync_state) == KnowledgeSyncState.FAILED.value
    assert "sha256 mismatch" in (status.last_error or "")
    public = status.to_public_dict()
    assert public["alignedWithCloud"] is False


def test_gcs_mode_without_mirror_does_not_fall_back_to_file_or_bundled(
    tmp_path: Path,
) -> None:
    from agent_service.knowledge_release import resolve_knowledge_index

    bundled = tmp_path / "bundled_chunks.json"
    bundled.write_text('{"version":1,"chunks":[]}', encoding="utf-8")
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=bundled,
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_tenant_id="tenant-a",
        knowledge_release_cache_dir=tmp_path / "empty-cache",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
        knowledge_release_mode="AUTO",
    )
    with pytest.raises(FileNotFoundError, match="No verified local knowledge snapshot"):
        resolve_knowledge_index(settings)


def test_legacy_index_only_status_is_not_aligned(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
    )
    syncer = KnowledgeReleaseSyncer(settings)
    with syncer._lock:
        syncer._status.cloud_active_release_id = "release-legacy"
        syncer._status.mirrored_release_id = "release-legacy"
        syncer._status.loaded_release_id = "release-legacy"
        syncer._status.sync_state = KnowledgeSyncState.IN_SYNC
        syncer._status.runtime_inventory_complete = False
        syncer._refresh_behind_flag()
    public = syncer.status.to_public_dict()
    assert public["qaSnapshotComplete"] is False
    assert public["alignedWithCloud"] is False
    assert public["indexOnlyMirror"] is True
    assert public["behindCloud"] is True


def test_acl_artifact_paths_are_inventory_eligible(tmp_path: Path) -> None:
    assert is_qa_sync_relative_path("acl/groups.json")
    release_dir = tmp_path / "release-acl"
    _write_minimal_release(release_dir, "release-acl", "tenant-a")
    acl_path = release_dir / "acl" / "groups.json"
    acl_path.parent.mkdir(parents=True, exist_ok=True)
    acl_path.write_text('{"groups":["grp_public"]}', encoding="utf-8")
    generations = {
        "index/chunks.json": 1,
        "sources/doc-a.md": 2,
        "acl/groups.json": 3,
    }
    inventory = build_runtime_artifact_inventory(
        generations=generations,
        release_dir=release_dir,
    )
    paths = {entry.relative_path for entry in inventory}
    assert "acl/groups.json" in paths
    assert "index/chunks.json" in paths


def test_cross_tenant_cache_paths_do_not_collide(tmp_path: Path) -> None:
    tenant_a = tenant_release_cache_dir(tmp_path, "tenant-a", "release-1")
    tenant_b = tenant_release_cache_dir(tmp_path, "tenant-b", "release-1")
    assert tenant_a != tenant_b
    tenant_a.mkdir(parents=True)
    (tenant_a / "manifest.json").write_text('{"releaseId":"release-1"}', encoding="utf-8")
    # Tenant B must not resolve tenant A's mirror.
    assert (
        resolve_mirrored_release_dir(
            tmp_path, tenant_id="tenant-b", release_id="release-1"
        )
        is None
    )
    assert (
        resolve_mirrored_release_dir(
            tmp_path, tenant_id="tenant-a", release_id="release-1"
        )
        == tenant_a
    )


def test_follow_cloud_sync_updates_mirror_without_swapping_loaded_until_reload(
    tmp_path: Path,
) -> None:
    """In-flight / pre-reload: mirror advances; loaded stays until FOLLOW handler."""
    tenant_id = "tenant-a"
    old_id = "release-old"
    new_id = "release-new"
    cache = tmp_path / "cache"
    client = FakeStorageClient()
    refs: dict[str, object] = {}
    for release_id in (old_id, new_id):
        source = tmp_path / "source" / release_id
        index_path = _write_minimal_release(source, release_id, tenant_id)
        artifact = inspect_index_artifact(index_path)
        published = publish_release_directory(
            source,
            bucket_name="knowledge",
            object_prefix="knowledge-releases",
            tenant_id=tenant_id,
            release_id=release_id,
            client=client,
        )
        refs[release_id] = _reference_for(
            release_id=release_id,
            tenant_id=tenant_id,
            published=published,
            artifact=artifact,
        )

    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_gcs_prefix="knowledge-releases",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=cache,
        knowledge_release_selection_mode="FOLLOW_CLOUD",
        knowledge_release_require_vectors=True,
    )
    syncer = KnowledgeReleaseSyncer(
        settings,
        storage_client=client,
        loaded_release_id=old_id,
    )

    def _read_ref(_settings: object, *, release_id: str | None = None, client: object = None):
        del _settings, client
        return refs[release_id or new_id]

    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        side_effect=_read_ref,
    ):
        status = syncer.sync_now()

    assert status.cloud_active_release_id == new_id
    assert status.mirrored_release_id == new_id
    # Loaded stays on the in-flight / previous release until hot-reload.
    assert status.loaded_release_id == old_id
    assert is_verified_qa_snapshot(tenant_release_cache_dir(cache, tenant_id, new_id))
