"""§5 acceptance simulations for knowledge release sync (no live GCS).

Covers the control-plane story with FakeStorageClient + patched Firestore
release pointers:

1. Cloud active advances → inventory download → mirror advances → FOLLOW_CLOUD
   reload → loaded matches → alignedWithCloud only when all three match and
   runtime inventory is complete.
2. PINNED: cloud/mirror can advance while loaded stays on the pin.
3. Sync failure after a verified snapshot keeps that snapshot usable; with no
   snapshot, GCS mode refuses knowledge Q&A (no FILE/bundled silent fallback).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from test_knowledge_release_sync import (
    FakeStorageClient,
    _reference_for,
    _sync_state,
    _write_minimal_release,
)

from agent_service.knowledge_release import resolve_knowledge_index
from agent_service.knowledge_release_cache import tenant_release_cache_dir
from agent_service.knowledge_release_gcs import publish_release_directory
from agent_service.knowledge_release_sync import (
    KnowledgeReleaseSelectionMode,
    KnowledgeReleaseSyncer,
    KnowledgeSyncState,
    is_verified_qa_snapshot,
)
from agent_service.release_artifacts import inspect_index_artifact
from agent_service.settings import RagSettings


def _publish(
    tmp_path: Path,
    *,
    release_id: str,
    tenant_id: str,
    client: FakeStorageClient,
) -> tuple[object, object]:
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
    return _reference_for(
        release_id=release_id,
        tenant_id=tenant_id,
        published=published,
        artifact=artifact,
    ), artifact


def test_acceptance_follow_cloud_pointer_change_aligns_three_columns(
    tmp_path: Path,
) -> None:
    tenant_id = "tenant-a"
    old_id = "release-old"
    new_id = "release-new"
    cache = tmp_path / "cache"
    client = FakeStorageClient()
    refs: dict[str, object] = {}
    for release_id in (old_id, new_id):
        refs[release_id], _ = _publish(
            tmp_path,
            release_id=release_id,
            tenant_id=tenant_id,
            client=client,
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
    syncer = KnowledgeReleaseSyncer(settings, storage_client=client)
    active = {"id": old_id}

    def _read_ref(_settings: object, *, release_id: str | None = None, client: object = None):
        del _settings, client
        return refs[release_id or active["id"]]

    def _on_ready(ready_id: str, _mirror_dir: Path) -> None:
        syncer.set_loaded_release_id(ready_id)

    syncer.set_follow_cloud_ready_handler(_on_ready)

    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        side_effect=_read_ref,
    ):
        first = syncer.sync_now()
        assert first.cloud_active_release_id == old_id
        assert first.mirrored_release_id == old_id
        assert first.loaded_release_id == old_id
        assert first.to_public_dict()["alignedWithCloud"] is True

        # Inventory incomplete ⇒ not aligned even if IDs match.
        syncer._status.runtime_inventory_complete = False
        assert syncer.status.to_public_dict()["alignedWithCloud"] is False
        syncer._status.runtime_inventory_complete = True

        active["id"] = new_id
        second = syncer.sync_now()

    assert second.cloud_active_release_id == new_id
    assert second.mirrored_release_id == new_id
    assert second.loaded_release_id == new_id
    public = second.to_public_dict()
    assert public["alignedWithCloud"] is True
    assert public["qaSnapshotComplete"] is True
    assert is_verified_qa_snapshot(tenant_release_cache_dir(cache, tenant_id, new_id))


def test_acceptance_pinned_keeps_loaded_while_cloud_mirror_advances(
    tmp_path: Path,
) -> None:
    tenant_id = "tenant-a"
    cloud_id = "release-cloud"
    pinned_id = "release-pinned"
    cache = tmp_path / "cache"
    client = FakeStorageClient()
    refs: dict[str, object] = {}
    for release_id in (cloud_id, pinned_id):
        refs[release_id], _ = _publish(
            tmp_path,
            release_id=release_id,
            tenant_id=tenant_id,
            client=client,
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
        return refs[release_id or cloud_id]

    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        side_effect=_read_ref,
    ):
        status = syncer.sync_now()

    assert status.cloud_active_release_id == cloud_id
    assert status.mirrored_release_id == pinned_id
    assert status.loaded_release_id == pinned_id
    assert status.to_public_dict()["alignedWithCloud"] is False
    assert is_verified_qa_snapshot(tenant_release_cache_dir(cache, tenant_id, pinned_id))
    # Cloud active is also mirrored for prune safety when FOLLOW would need it,
    # but loaded must not jump to cloud_id in PINNED mode.
    assert status.loaded_release_id != cloud_id


def test_acceptance_failed_sync_keeps_last_verified_snapshot_usable(
    tmp_path: Path,
) -> None:
    tenant_id = "tenant-a"
    good_id = "release-good"
    bad_id = "release-bad"
    cache = tmp_path / "cache"
    client = FakeStorageClient()
    refs: dict[str, object] = {}
    refs[good_id], _ = _publish(
        tmp_path,
        release_id=good_id,
        tenant_id=tenant_id,
        client=client,
    )
    refs[bad_id], _artifact = _publish(
        tmp_path,
        release_id=bad_id,
        tenant_id=tenant_id,
        client=client,
    )
    # Corrupt the newly published bad release so the next sync fails closed.
    corrupted_key = next(
        name
        for (name, _gen) in client.bucket_instance.objects
        if f"/{bad_id}/" in name and name.endswith("sources/doc-a.md")
    )
    gen = client.bucket_instance.latest_generations[corrupted_key]
    original = client.bucket_instance.objects[(corrupted_key, gen)]
    client.bucket_instance.objects[(corrupted_key, gen)] = b"X" * len(original)

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
    syncer = KnowledgeReleaseSyncer(settings, storage_client=client)
    active = {"id": good_id}

    def _read_ref(_settings: object, *, release_id: str | None = None, client: object = None):
        del _settings, client
        return refs[release_id or active["id"]]

    def _on_ready(ready_id: str, _mirror_dir: Path) -> None:
        syncer.set_loaded_release_id(ready_id)

    syncer.set_follow_cloud_ready_handler(_on_ready)

    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        side_effect=_read_ref,
    ):
        good = syncer.sync_now()
        assert good.to_public_dict()["alignedWithCloud"] is True
        good_mirror = tenant_release_cache_dir(cache, tenant_id, good_id)
        assert is_verified_qa_snapshot(good_mirror)

        active["id"] = bad_id
        failed = syncer.sync_now()

    assert _sync_state(failed.sync_state) == KnowledgeSyncState.FAILED.value
    assert failed.to_public_dict()["alignedWithCloud"] is False
    # Last verified snapshot remains on disk and usable for Q&A resolution.
    assert is_verified_qa_snapshot(good_mirror)
    settings_for_resolve = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=cache,
        knowledge_active_release_id=good_id,
        knowledge_release_selection_mode="PINNED",
        knowledge_release_require_vectors=True,
    )
    resolved = resolve_knowledge_index(settings_for_resolve)
    assert resolved is not None
    assert good_id in str(resolved)

    # No snapshot at all ⇒ knowledge Q&A unavailable (fail closed).
    empty = RagSettings(
        data_dir=tmp_path / "empty-root",
        index_path=tmp_path / "empty-root" / "missing.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_tenant_id=tenant_id,
        knowledge_release_cache_dir=tmp_path / "empty-cache",
        knowledge_release_require_vectors=True,
    )
    with pytest.raises(FileNotFoundError, match="No verified local knowledge snapshot"):
        resolve_knowledge_index(empty)


def test_acceptance_aligned_requires_matching_ids_and_inventory(
    tmp_path: Path,
) -> None:
    """Unit-level contract: alignedWithCloud is a four-way conjunction."""
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_cache_dir=tmp_path / "cache",
        knowledge_release_tenant_id="tenant-a",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="knowledge",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
    )
    syncer = KnowledgeReleaseSyncer(settings)
    with syncer._lock:
        syncer._status.selection_mode = KnowledgeReleaseSelectionMode.FOLLOW_CLOUD
        syncer._status.cloud_active_release_id = "r1"
        syncer._status.mirrored_release_id = "r1"
        syncer._status.loaded_release_id = "r1"
        syncer._status.sync_state = KnowledgeSyncState.IN_SYNC
        syncer._status.runtime_inventory_complete = True
        syncer._status.behind_cloud = False
    assert syncer.status.to_public_dict()["alignedWithCloud"] is True

    with syncer._lock:
        syncer._status.loaded_release_id = "r0"
    assert syncer.status.to_public_dict()["alignedWithCloud"] is False

    with syncer._lock:
        syncer._status.loaded_release_id = "r1"
        syncer._status.runtime_inventory_complete = False
    assert syncer.status.to_public_dict()["alignedWithCloud"] is False

    with syncer._lock:
        syncer._status.runtime_inventory_complete = True
        syncer._status.cloud_active_release_id = "r2"
        syncer._status.mirrored_release_id = "r1"
        syncer._status.loaded_release_id = "r1"
        syncer._status.behind_cloud = True
    assert syncer.status.to_public_dict()["alignedWithCloud"] is False

    # LOCAL_SANDBOX / PINNED never claim cloud production alignment.
    with syncer._lock:
        syncer._status.runtime_inventory_complete = True
        syncer._status.selection_mode = KnowledgeReleaseSelectionMode.LOCAL_SANDBOX
    assert syncer.status.to_public_dict()["alignedWithCloud"] is False
    with syncer._lock:
        syncer._status.selection_mode = KnowledgeReleaseSelectionMode.PINNED
    assert syncer.status.to_public_dict()["matchesCloudProduction"] is False


def test_acceptance_control_plane_unavailable_keeps_loaded_snapshot(
    tmp_path: Path,
) -> None:
    """When Firestore control plane fails, last loaded/mirrored snapshot stays."""
    tenant_id = "tenant-a"
    good_id = "release-good"
    cache = tmp_path / "cache"
    client = FakeStorageClient()
    refs: dict[str, object] = {}
    refs[good_id], _ = _publish(
        tmp_path,
        release_id=good_id,
        tenant_id=tenant_id,
        client=client,
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
    syncer = KnowledgeReleaseSyncer(settings, storage_client=client)

    def _on_ready(ready_id: str, _mirror_dir: Path) -> None:
        syncer.set_loaded_release_id(ready_id)

    syncer.set_follow_cloud_ready_handler(_on_ready)

    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        return_value=refs[good_id],
    ):
        good = syncer.sync_now()
    assert good.to_public_dict()["alignedWithCloud"] is True
    loaded_before = good.loaded_release_id

    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        side_effect=RuntimeError("firestore unavailable"),
    ):
        unavailable = syncer.sync_now()

    assert _sync_state(unavailable.sync_state) == (
        KnowledgeSyncState.CONTROL_UNAVAILABLE.value
    )
    assert unavailable.loaded_release_id == loaded_before
    assert unavailable.to_public_dict()["alignedWithCloud"] is False
    assert is_verified_qa_snapshot(tenant_release_cache_dir(cache, tenant_id, good_id))


def test_acceptance_enospc_mid_download_keeps_last_verified_snapshot(
    tmp_path: Path,
) -> None:
    """§5.4: disk-full mid-download fails closed; no partial promote."""
    import errno

    from test_knowledge_release_sync import FakeBlob

    tenant_id = "tenant-a"
    good_id = "release-good"
    full_id = "release-disk-full"
    cache = tmp_path / "cache"
    client = FakeStorageClient()
    refs: dict[str, object] = {}
    for release_id in (good_id, full_id):
        refs[release_id], _ = _publish(
            tmp_path,
            release_id=release_id,
            tenant_id=tenant_id,
            client=client,
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
    syncer = KnowledgeReleaseSyncer(settings, storage_client=client)
    active = {"id": good_id}

    def _read_ref(_settings: object, *, release_id: str | None = None, client: object = None):
        del _settings, client
        return refs[release_id or active["id"]]

    def _on_ready(ready_id: str, _mirror_dir: Path) -> None:
        syncer.set_loaded_release_id(ready_id)

    syncer.set_follow_cloud_ready_handler(_on_ready)
    original_download = FakeBlob.download_to_filename
    write_calls = {"n": 0}

    def _enospc_after_partial(self: FakeBlob, filename: str) -> None:
        write_calls["n"] += 1
        # Allow the first object (manifest) so staging is partially populated,
        # then fail closed mid-inventory like a full disk.
        if write_calls["n"] >= 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return original_download(self, filename)

    with patch(
        "agent_service.knowledge_release_sync.read_firestore_release_reference",
        side_effect=_read_ref,
    ):
        good = syncer.sync_now()
        assert good.to_public_dict()["alignedWithCloud"] is True
        good_mirror = tenant_release_cache_dir(cache, tenant_id, good_id)
        assert is_verified_qa_snapshot(good_mirror)
        loaded_before = syncer.loaded_release_id

        active["id"] = full_id
        write_calls["n"] = 0
        with patch.object(FakeBlob, "download_to_filename", _enospc_after_partial):
            failed = syncer.sync_now()

    assert _sync_state(failed.sync_state) == KnowledgeSyncState.FAILED.value
    assert failed.to_public_dict()["alignedWithCloud"] is False
    assert failed.loaded_release_id == loaded_before
    assert is_verified_qa_snapshot(good_mirror)

    failed_mirror = tenant_release_cache_dir(cache, tenant_id, full_id)
    assert not is_verified_qa_snapshot(failed_mirror)
    # Staging leftovers must not remain as a promotable release directory.
    releases_root = cache / "tenants" / tenant_id / "releases"
    if releases_root.is_dir():
        staging = [p for p in releases_root.iterdir() if p.name.startswith(".staging-")]
        assert staging == []
    assert write_calls["n"] >= 2
