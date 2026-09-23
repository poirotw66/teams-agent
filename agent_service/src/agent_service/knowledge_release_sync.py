"""Background GCS → local knowledge-release mirror syncer.

Sync runs at startup, on a poll interval, and via ``sync_now``. Playground Q&A
loads only from verified local snapshots; this module never sits on the request
path.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Self

from knowledge_core.artifacts import MANIFEST_FILENAME
from knowledge_core.release_artifacts import validate_release_artifacts
from knowledge_core.runtime_inventory import (
    has_complete_runtime_inventory,
    parse_runtime_artifact_inventory,
    verification_hash_for_inventory,
)

from .knowledge_release_cache import (
    VERIFIED_MARKER_FILENAME,
    is_verified_release_dir,
    resolve_local_release_dir,
    sync_lock_path,
    sync_status_path,
    tenant_release_dir,
    tenant_releases_root,
    verified_marker_path,
)
from .knowledge_release_control import (
    KnowledgeReleaseReference,
    read_firestore_release_reference,
)
from .knowledge_release_gcs import download_release_runtime_snapshot
from .settings import RagSettings

logger = logging.getLogger(__name__)

_KEPT_VERIFIED_RELEASES = 2


class KnowledgeSelectionMode(str, Enum):
    FOLLOW_CLOUD = "FOLLOW_CLOUD"
    PINNED = "PINNED"
    LOCAL_SANDBOX = "LOCAL_SANDBOX"


# Public aliases matching call sites / tests.
KnowledgeReleaseSelectionMode = KnowledgeSelectionMode


class KnowledgeSyncState(str, Enum):
    IN_SYNC = "IN_SYNC"
    DOWNLOADING = "DOWNLOADING"
    VALIDATING = "VALIDATING"
    FAILED = "FAILED"
    CONTROL_UNAVAILABLE = "CONTROL_UNAVAILABLE"


KnowledgeReleaseSyncState = KnowledgeSyncState


@dataclass
class KnowledgeReleaseSyncStatus:
    cloud_active_release_id: str | None = None
    mirrored_release_id: str | None = None
    loaded_release_id: str | None = None
    selection_mode: KnowledgeSelectionMode = KnowledgeSelectionMode.FOLLOW_CLOUD
    sync_state: KnowledgeSyncState = KnowledgeSyncState.CONTROL_UNAVAILABLE
    last_successful_sync_at: str | None = None
    artifact_count: int = 0
    verification_hash: str | None = None
    runtime_inventory_complete: bool = False
    last_error: str | None = None
    behind_cloud: bool = False
    detail: str | None = None

    @property
    def qa_snapshot_complete(self) -> bool:
        return self.runtime_inventory_complete

    def to_public_dict(self) -> dict[str, object]:
        sync_state = (
            self.sync_state.value
            if isinstance(self.sync_state, KnowledgeSyncState)
            else str(self.sync_state)
        )
        selection = (
            self.selection_mode.value
            if isinstance(self.selection_mode, KnowledgeSelectionMode)
            else str(self.selection_mode)
        )
        # Only FOLLOW_CLOUD may claim cloud production alignment. PINNED and
        # LOCAL_SANDBOX can mirror cloud artifacts but must never advertise
        # "matches cloud production" (spec §3 status honesty).
        aligned = (
            selection == KnowledgeSelectionMode.FOLLOW_CLOUD.value
            and sync_state == KnowledgeSyncState.IN_SYNC.value
            and bool(self.cloud_active_release_id)
            and self.cloud_active_release_id == self.mirrored_release_id
            and self.mirrored_release_id == self.loaded_release_id
            and self.runtime_inventory_complete
            and not self.behind_cloud
        )
        index_only = bool(self.mirrored_release_id) and not self.runtime_inventory_complete
        return {
            "cloudActiveReleaseId": self.cloud_active_release_id,
            "mirroredReleaseId": self.mirrored_release_id,
            "loadedReleaseId": self.loaded_release_id,
            "selectionMode": selection,
            "syncState": sync_state,
            "lastSuccessfulSyncAt": self.last_successful_sync_at,
            "artifactCount": self.artifact_count,
            "verificationHash": self.verification_hash,
            "runtimeInventoryComplete": self.runtime_inventory_complete,
            "qaSnapshotComplete": self.runtime_inventory_complete,
            "indexOnlyMirror": index_only,
            "behindCloud": self.behind_cloud,
            "lastError": self.last_error,
            "detail": self.detail,
            "matchesCloudProduction": aligned,
            "alignedWithCloud": aligned,
        }


@dataclass(frozen=True)
class _MirrorResult:
    release_dir: Path
    inventory_complete: bool
    artifact_count: int
    verification_hash: str | None


@dataclass
class KnowledgeReleaseSyncer:
    """Single-instance syncer for one tenant's GCS mirrors."""

    settings: RagSettings
    firestore_client: Any | None = None
    storage_client: Any | None = None
    loaded_release_id: str | None = None
    _status: KnowledgeReleaseSyncStatus = field(
        default_factory=KnowledgeReleaseSyncStatus
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _poll_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _on_follow_cloud_ready: Callable[[str, Path], None] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._status.selection_mode = resolve_selection_mode(self.settings)
        self._status.loaded_release_id = self.loaded_release_id
        persisted = _read_status_file(self._cache_root(), self._tenant_id())
        if persisted is not None:
            self._merge_persisted_status(persisted)

    @property
    def status(self) -> KnowledgeReleaseSyncStatus:
        with self._lock:
            return KnowledgeReleaseSyncStatus(**asdict(self._status))

    def start_background(self) -> None:
        if self._poll_thread is not None and self._poll_thread.is_alive():
            return
        interval = max(1, int(self.settings.knowledge_release_sync_interval_seconds))
        self._stop_event.clear()

        def _loop() -> None:
            while not self._stop_event.wait(interval):
                try:
                    self.sync_once()
                except Exception:  # noqa: BLE001 - background boundary
                    logger.exception("Knowledge release background sync failed.")

        self._poll_thread = threading.Thread(
            target=_loop,
            name="knowledge-release-sync",
            daemon=True,
        )
        self._poll_thread.start()

    def stop_background(self) -> None:
        self._stop_event.set()
        thread = self._poll_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._poll_thread = None

    start_background_polling = start_background
    stop_background_polling = stop_background

    def sync_now(self) -> KnowledgeReleaseSyncStatus:
        return self.sync_once()

    def sync_once(self) -> KnowledgeReleaseSyncStatus:
        selection = resolve_selection_mode(self.settings)
        if selection == KnowledgeSelectionMode.LOCAL_SANDBOX:
            with self._lock:
                self._status.selection_mode = selection
                self._status.sync_state = KnowledgeSyncState.IN_SYNC
                self._status.behind_cloud = False
                self._status.last_error = None
                return KnowledgeReleaseSyncStatus(**asdict(self._status))

        lock_path = sync_lock_path(self._cache_root(), self._tenant_id())
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with _FileLock(lock_path):
            return self._sync_locked(selection)

    def set_loaded_release_id(self, release_id: str | None) -> None:
        with self._lock:
            self.loaded_release_id = release_id
            self._status.loaded_release_id = release_id
            self._refresh_behind_flag()
            self._persist_status()

    mark_loaded_release = set_loaded_release_id

    def set_follow_cloud_ready_handler(
        self,
        handler: Callable[[str, Path], None] | None,
    ) -> None:
        """Optional hook invoked after FOLLOW_CLOUD mirrors a new release."""
        self._on_follow_cloud_ready = handler

    def resolve_loaded_release_id(
        self,
        *,
        cloud_active_release_id: str | None = None,
        mirrored_release_id: str | None = None,
    ) -> str | None:
        selection = resolve_selection_mode(self.settings)
        if selection == KnowledgeSelectionMode.PINNED:
            return self.settings.knowledge_active_release_id
        if selection == KnowledgeSelectionMode.LOCAL_SANDBOX:
            return self.settings.knowledge_active_release_id
        return mirrored_release_id or cloud_active_release_id

    def _sync_locked(
        self,
        selection: KnowledgeSelectionMode,
    ) -> KnowledgeReleaseSyncStatus:
        with self._lock:
            self._status.selection_mode = selection
            self._status.sync_state = KnowledgeSyncState.DOWNLOADING
            self._status.last_error = None
            self._persist_status()

        try:
            active_reference = read_firestore_release_reference(
                self.settings,
                release_id=None,
                client=self.firestore_client,
            )
        except Exception as error:  # noqa: BLE001 - control-plane boundary
            with self._lock:
                self._status.sync_state = KnowledgeSyncState.CONTROL_UNAVAILABLE
                self._status.last_error = str(error)
                self._refresh_behind_flag()
                self._persist_status()
                logger.warning("Knowledge control plane unavailable: %s", error)
                return KnowledgeReleaseSyncStatus(**asdict(self._status))

        cloud_active = active_reference.release_id
        targets: dict[str, KnowledgeReleaseReference] = {
            cloud_active: active_reference
        }
        pinned_id = self.settings.knowledge_active_release_id
        if selection == KnowledgeSelectionMode.PINNED and pinned_id:
            if pinned_id not in targets:
                targets[pinned_id] = read_firestore_release_reference(
                    self.settings,
                    release_id=pinned_id,
                    client=self.firestore_client,
                )

        try:
            mirror_results: dict[str, _MirrorResult] = {}
            for target_id, reference in targets.items():
                mirror_results[target_id] = self._mirror_release(reference)

            if selection == KnowledgeSelectionMode.FOLLOW_CLOUD:
                mirrored_id = cloud_active
            else:
                mirrored_id = pinned_id or cloud_active

            primary = mirror_results[mirrored_id]
            self._prune_old_mirrors(
                keep_ids={
                    release_id
                    for release_id in (
                        mirrored_id,
                        cloud_active,
                        pinned_id,
                        self.loaded_release_id,
                    )
                    if release_id
                }
            )
            # Preserve the Agent's actual loaded release until FOLLOW_CLOUD
            # hot-reload (or explicit set_loaded_release_id) updates it.
            actual_loaded = self.loaded_release_id
            with self._lock:
                self._status.cloud_active_release_id = cloud_active
                self._status.mirrored_release_id = mirrored_id
                self._status.loaded_release_id = actual_loaded
                self._status.sync_state = KnowledgeSyncState.IN_SYNC
                self._status.last_successful_sync_at = _utc_now_iso()
                self._status.artifact_count = primary.artifact_count
                self._status.verification_hash = primary.verification_hash
                self._status.runtime_inventory_complete = primary.inventory_complete
                self._status.detail = (
                    None
                    if primary.inventory_complete
                    else (
                        "Manifest lacks runtimeArtifacts; mirrored index only "
                        "(not a full QA snapshot)."
                    )
                )
                self._status.last_error = None
                self._refresh_behind_flag()
                self._persist_status()
            self._maybe_invoke_follow_cloud_ready(
                selection=selection,
                mirrored_id=mirrored_id,
                mirror_dir=primary.release_dir,
                inventory_complete=primary.inventory_complete,
                previous_loaded=actual_loaded,
            )
            return self.status
        except Exception as error:  # noqa: BLE001 - sync boundary
            with self._lock:
                self._status.sync_state = KnowledgeSyncState.FAILED
                self._status.last_error = str(error)
                self._status.cloud_active_release_id = cloud_active
                self._refresh_behind_flag()
                self._persist_status()
                logger.error("Knowledge release sync failed: %s", error)
                return KnowledgeReleaseSyncStatus(**asdict(self._status))

    def _maybe_invoke_follow_cloud_ready(
        self,
        *,
        selection: KnowledgeSelectionMode,
        mirrored_id: str,
        mirror_dir: Path,
        inventory_complete: bool,
        previous_loaded: str | None,
    ) -> None:
        if selection != KnowledgeSelectionMode.FOLLOW_CLOUD:
            return
        if not inventory_complete:
            logger.info(
                "FOLLOW_CLOUD mirror %s is index-only; skipping Agent hot-reload.",
                mirrored_id,
            )
            return
        if previous_loaded == mirrored_id:
            return
        handler = self._on_follow_cloud_ready
        if handler is None:
            return
        try:
            handler(mirrored_id, mirror_dir)
        except Exception:  # noqa: BLE001 - reload must not crash the syncer
            logger.exception(
                "FOLLOW_CLOUD reload handler failed for release %s",
                mirrored_id,
            )

    def _mirror_release(self, reference: KnowledgeReleaseReference) -> _MirrorResult:
        existing = resolve_local_release_dir(
            self._cache_root(),
            tenant_id=reference.tenant_id,
            release_id=reference.release_id,
            require_verified=True,
        )
        if existing is not None and _manifest_matches_reference(existing, reference):
            return _result_from_release_dir(existing)

        with self._lock:
            self._status.sync_state = KnowledgeSyncState.DOWNLOADING
            self._persist_status()

        final_dir = tenant_release_dir(
            self._cache_root(),
            reference.tenant_id,
            reference.release_id,
        )
        parent = final_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging_root = parent / f".staging-{uuid.uuid4().hex}"
        staging_release = staging_root / reference.release_id
        staging_release.mkdir(parents=True, exist_ok=True)

        try:
            _manifest_path, inventory, inventory_complete = (
                download_release_runtime_snapshot(
                    staging_release,
                    bucket_name=reference.bucket,
                    object_prefix=self.settings.knowledge_release_gcs_prefix,
                    tenant_id=reference.tenant_id,
                    release_id=reference.release_id,
                    manifest_generation=reference.manifest_generation,
                    index_generation=reference.index_generation,
                    client=self.storage_client,
                )
            )
            with self._lock:
                self._status.sync_state = KnowledgeSyncState.VALIDATING
                self._persist_status()

            artifact = validate_release_artifacts(
                staging_root,
                reference.release_id,
                require_vectors=self.settings.knowledge_release_require_vectors,
                expected_tenant_id=reference.tenant_id,
                expected_purpose=reference.purpose,
            )
            if artifact.sha256 != reference.index_sha256:
                raise ValueError(
                    "Downloaded knowledge index does not match its Firestore "
                    "release record."
                )
            if (
                artifact.chunk_count != reference.chunk_count
                or artifact.vector_count != reference.vector_count
            ):
                raise ValueError(
                    "Downloaded knowledge index counts do not match Firestore "
                    "metadata."
                )
            if (
                reference.embedding_model is not None
                and artifact.embedding_model != reference.embedding_model
            ):
                raise ValueError(
                    "Downloaded knowledge embedding model does not match Firestore."
                )
            if (
                reference.embedding_dimensions is not None
                and artifact.embedding_dimensions != reference.embedding_dimensions
            ):
                raise ValueError(
                    "Downloaded knowledge embedding dimensions do not match "
                    "Firestore."
                )

            marker = verified_marker_path(staging_release)
            marker.write_text(
                json.dumps(
                    {
                        "releaseId": reference.release_id,
                        "tenantId": reference.tenant_id,
                        "verifiedAt": _utc_now_iso(),
                        "runtimeInventoryComplete": inventory_complete,
                        "manifestGeneration": reference.manifest_generation,
                        "indexGeneration": reference.index_generation,
                        "indexSha256": reference.index_sha256,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            _make_tree_readonly(staging_release)
            _atomic_replace_directory(staging_release, final_dir)
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

        result = _result_from_release_dir(final_dir)
        if inventory is not None and inventory_complete:
            return _MirrorResult(
                release_dir=final_dir,
                inventory_complete=True,
                artifact_count=len(inventory),
                verification_hash=verification_hash_for_inventory(inventory),
            )
        return result

    def _prune_old_mirrors(self, *, keep_ids: set[str]) -> None:
        releases_root = tenant_releases_root(self._cache_root(), self._tenant_id())
        if not releases_root.is_dir():
            return
        verified: list[tuple[float, Path]] = []
        for child in releases_root.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name in keep_ids:
                continue
            if not is_verified_release_dir(child):
                continue
            verified.append((child.stat().st_mtime, child))
        verified.sort(reverse=True)
        retained = len(keep_ids)
        for _mtime, path in verified:
            if retained >= _KEPT_VERIFIED_RELEASES:
                _chmod_tree_writable(path)
                shutil.rmtree(path, ignore_errors=True)
            else:
                retained += 1

    def _cache_root(self) -> Path:
        return self.settings.knowledge_release_cache_dir or (
            self.settings.data_dir / "knowledge_cache"
        )

    def _tenant_id(self) -> str:
        return self.settings.knowledge_release_tenant_id

    def _refresh_behind_flag(self) -> None:
        cloud = self._status.cloud_active_release_id
        loaded = self._status.loaded_release_id
        mirrored = self._status.mirrored_release_id
        # Spec §1 / §3.3: incomplete QA inventory (legacy index-only) must not be
        # treated as caught up with cloud production, even when release IDs match.
        inventory_gap = bool(cloud) and not self._status.runtime_inventory_complete
        self._status.behind_cloud = bool(
            cloud
            and (
                loaded != cloud
                or mirrored != cloud
                or inventory_gap
            )
        )

    def _persist_status(self) -> None:
        path = sync_status_path(self._cache_root(), self._tenant_id())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._status.to_public_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _merge_persisted_status(self, payload: dict[str, object]) -> None:
        self._status.cloud_active_release_id = _optional_str(
            payload.get("cloudActiveReleaseId")
        )
        self._status.mirrored_release_id = _optional_str(
            payload.get("mirroredReleaseId")
        )
        if self.loaded_release_id is None:
            self._status.loaded_release_id = _optional_str(
                payload.get("loadedReleaseId")
            )
            self.loaded_release_id = self._status.loaded_release_id
        self._status.last_successful_sync_at = _optional_str(
            payload.get("lastSuccessfulSyncAt")
        )
        artifact_count = payload.get("artifactCount")
        if isinstance(artifact_count, int):
            self._status.artifact_count = artifact_count
        self._status.verification_hash = _optional_str(payload.get("verificationHash"))
        self._status.runtime_inventory_complete = bool(
            payload.get("runtimeInventoryComplete") or payload.get("qaSnapshotComplete")
        )
        sync_state = _optional_str(payload.get("syncState"))
        if sync_state:
            try:
                self._status.sync_state = KnowledgeSyncState(sync_state)
            except ValueError:
                self._status.sync_state = KnowledgeSyncState.FAILED
        selection_mode = _optional_str(payload.get("selectionMode"))
        if selection_mode:
            try:
                self._status.selection_mode = KnowledgeSelectionMode(selection_mode)
            except ValueError:
                pass
        self._status.detail = _optional_str(payload.get("detail"))
        self._refresh_behind_flag()


def resolve_selection_mode(settings: RagSettings) -> KnowledgeSelectionMode:
    explicit = (settings.knowledge_release_selection_mode or "").strip().upper()
    if explicit:
        try:
            return KnowledgeSelectionMode(explicit)
        except ValueError as error:
            raise ValueError(
                "KNOWLEDGE_RELEASE_SELECTION_MODE must be FOLLOW_CLOUD, "
                "PINNED, or LOCAL_SANDBOX."
            ) from error
    if settings.knowledge_release_store_mode != "GCS":
        return KnowledgeSelectionMode.LOCAL_SANDBOX
    if settings.knowledge_active_release_id:
        return KnowledgeSelectionMode.PINNED
    return KnowledgeSelectionMode.FOLLOW_CLOUD


def is_verified_qa_snapshot(release_dir: Path) -> bool:
    return is_verified_release_dir(release_dir)


def read_sync_status(
    cache_root: Path,
    tenant_id: str,
) -> KnowledgeReleaseSyncStatus | None:
    payload = _read_status_file(cache_root, tenant_id)
    if payload is None:
        return None
    selection_raw = _optional_str(payload.get("selectionMode"))
    sync_raw = _optional_str(payload.get("syncState"))
    try:
        selection_mode = (
            KnowledgeSelectionMode(selection_raw)
            if selection_raw
            else KnowledgeSelectionMode.FOLLOW_CLOUD
        )
    except ValueError:
        selection_mode = KnowledgeSelectionMode.FOLLOW_CLOUD
    try:
        sync_state = (
            KnowledgeSyncState(sync_raw)
            if sync_raw
            else KnowledgeSyncState.CONTROL_UNAVAILABLE
        )
    except ValueError:
        sync_state = KnowledgeSyncState.CONTROL_UNAVAILABLE
    return KnowledgeReleaseSyncStatus(
        cloud_active_release_id=_optional_str(payload.get("cloudActiveReleaseId")),
        mirrored_release_id=_optional_str(payload.get("mirroredReleaseId")),
        loaded_release_id=_optional_str(payload.get("loadedReleaseId")),
        selection_mode=selection_mode,
        sync_state=sync_state,
        last_successful_sync_at=_optional_str(payload.get("lastSuccessfulSyncAt")),
        artifact_count=int(payload["artifactCount"])
        if isinstance(payload.get("artifactCount"), int)
        else 0,
        verification_hash=_optional_str(payload.get("verificationHash")),
        runtime_inventory_complete=bool(
            payload.get("runtimeInventoryComplete") or payload.get("qaSnapshotComplete")
        ),
        behind_cloud=bool(payload.get("behindCloud")),
        last_error=_optional_str(payload.get("lastError")),
        detail=_optional_str(payload.get("detail")),
    )


def build_knowledge_release_syncer(
    settings: RagSettings,
    *,
    firestore_client: Any | None = None,
    storage_client: Any | None = None,
    loaded_release_id: str | None = None,
) -> KnowledgeReleaseSyncer:
    return KnowledgeReleaseSyncer(
        settings=settings,
        firestore_client=firestore_client,
        storage_client=storage_client,
        loaded_release_id=loaded_release_id,
    )


class _FileLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Any | None = None

    def __enter__(self) -> Self:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows
            pass
        self._handle = handle
        return self

    def __exit__(self, *args: object) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:  # pragma: no cover - Windows
            pass
        handle.close()
        self._handle = None


def _result_from_release_dir(release_dir: Path) -> _MirrorResult:
    manifest_path = release_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("Mirrored release manifest is invalid.")
    inventory = parse_runtime_artifact_inventory(manifest)
    inventory_complete = has_complete_runtime_inventory(manifest)
    if inventory:
        return _MirrorResult(
            release_dir=release_dir,
            inventory_complete=inventory_complete,
            artifact_count=len(inventory),
            verification_hash=verification_hash_for_inventory(inventory),
        )
    return _MirrorResult(
        release_dir=release_dir,
        inventory_complete=False,
        artifact_count=1,
        verification_hash=None,
    )


def _atomic_replace_directory(staging: Path, final_dir: Path) -> None:
    parent = final_dir.parent
    backup: Path | None = None
    if final_dir.exists():
        backup = parent / f".{final_dir.name}.bak.{uuid.uuid4().hex}"
        final_dir.rename(backup)
    try:
        staging.rename(final_dir)
    except Exception:
        if backup is not None and backup.exists() and not final_dir.exists():
            backup.rename(final_dir)
        raise
    if backup is not None:
        _chmod_tree_writable(backup)
        shutil.rmtree(backup, ignore_errors=True)


def _make_tree_readonly(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            mode = path.stat().st_mode
            path.chmod(mode & ~0o222 & ~0o111)


def _chmod_tree_writable(root: Path) -> None:
    for path in root.rglob("*"):
        if path.exists():
            mode = path.stat().st_mode
            path.chmod(mode | 0o200)


def _manifest_matches_reference(
    release_dir: Path,
    reference: KnowledgeReleaseReference,
) -> bool:
    marker = verified_marker_path(release_dir)
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return (
        payload.get("releaseId") == reference.release_id
        and payload.get("tenantId") == reference.tenant_id
        and payload.get("manifestGeneration") == reference.manifest_generation
        and payload.get("indexGeneration") == reference.index_generation
        and payload.get("indexSha256") == reference.index_sha256
    )


def _read_status_file(cache_root: Path, tenant_id: str) -> dict[str, object] | None:
    path = sync_status_path(cache_root, tenant_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "VERIFIED_MARKER_FILENAME",
    "KnowledgeReleaseSelectionMode",
    "KnowledgeReleaseSyncState",
    "KnowledgeReleaseSyncStatus",
    "KnowledgeReleaseSyncer",
    "KnowledgeSelectionMode",
    "KnowledgeSyncState",
    "build_knowledge_release_syncer",
    "is_verified_qa_snapshot",
    "read_sync_status",
    "resolve_selection_mode",
]
