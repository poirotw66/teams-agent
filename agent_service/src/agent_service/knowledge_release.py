from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from knowledge_core.release_pointer import (
    ACTIVE_RELEASE_FILENAME,
    read_active_release_id,
    release_index_path,
    write_active_release_pointer,
)

from .knowledge_release_cache import resolve_mirrored_release_dir
from .knowledge_release_sync import (
    KnowledgeReleaseSelectionMode,
    KnowledgeReleaseSyncStatus,
    is_verified_qa_snapshot,
    read_sync_status,
    resolve_selection_mode,
)
from .release_artifacts import (
    MANIFEST_FILENAME,
    KnowledgeIndexArtifact,
    KnowledgeReleaseValidationError,
    validate_release_artifacts,
)
from .settings import RagSettings

logger = logging.getLogger(__name__)

__all__ = [
    "ACTIVE_RELEASE_FILENAME",
    "ResolvedKnowledgeIndex",
    "manifest_file_search_store",
    "read_active_release_id",
    "release_index_path",
    "resolve_knowledge_index",
    "write_active_release_pointer",
]


@dataclass(frozen=True)
class ResolvedKnowledgeIndex:
    index_path: Path
    release_id: str | None
    source: str
    artifact: KnowledgeIndexArtifact | None = None
    release_dir: Path | None = None
    file_search_store: str | None = None


def _load_portal_release_artifact(
    settings: RagSettings,
    *,
    release_dir: Path,
    release_id: str,
    candidate: Path,
) -> KnowledgeIndexArtifact | None:
    manifest_exists = (candidate.parents[1] / MANIFEST_FILENAME).is_file()
    requires_validation = (
        settings.knowledge_release_require_manifest
        or settings.knowledge_release_require_vectors
    )
    if requires_validation:
        return validate_release_artifacts(
            release_dir,
            release_id,
            require_vectors=settings.knowledge_release_require_vectors,
        )
    if not manifest_exists:
        return None
    try:
        return validate_release_artifacts(
            release_dir,
            release_id,
            require_vectors=False,
        )
    except KnowledgeReleaseValidationError as error:
        logger.warning(
            "Loading release %s without optional manifest validation: %s",
            release_id,
            error,
        )
        return None


def _resolve_local_portal_release(
    settings: RagSettings,
    *,
    release_dir: Path,
    release_id: str,
    mode: str,
) -> ResolvedKnowledgeIndex | None:
    candidate = release_index_path(release_dir, release_id)
    if candidate.is_file():
        artifact = _load_portal_release_artifact(
            settings,
            release_dir=release_dir,
            release_id=release_id,
            candidate=candidate,
        )
        logger.info(
            "Loading knowledge index from portal release %s at %s",
            release_id,
            candidate,
        )
        return ResolvedKnowledgeIndex(
            index_path=candidate,
            release_id=release_id,
            source="portal_release",
            artifact=artifact,
            release_dir=release_dir,
            file_search_store=manifest_file_search_store(candidate.parents[1]),
        )
    if mode == "PORTAL":
        raise FileNotFoundError(f"Active knowledge release index not found: {candidate}")
    logger.warning(
        "Active release %s was configured but index file is missing: %s",
        release_id,
        candidate,
    )
    return None


def resolve_knowledge_index(
    settings: RagSettings,
    *,
    release_id_override: str | None = None,
) -> ResolvedKnowledgeIndex:
    mode = settings.knowledge_release_mode.upper()
    if mode not in {"BUNDLED", "PORTAL", "AUTO"}:
        raise ValueError("KNOWLEDGE_RELEASE_MODE must be BUNDLED, PORTAL, or AUTO.")

    release_dir = settings.knowledge_release_dir or (settings.data_dir / "releases")
    if settings.knowledge_release_store_mode == "GCS":
        selection = resolve_selection_mode(settings)
        if selection is KnowledgeReleaseSelectionMode.LOCAL_SANDBOX:
            return _resolve_local_sandbox_under_gcs_store(
                settings,
                release_dir=release_dir,
                release_id_override=release_id_override,
                mode=mode,
            )
        return _resolve_gcs_mirrored_knowledge_index(
            settings,
            release_id=release_id_override or settings.knowledge_active_release_id,
            selection=selection,
        )

    explicit_release_id = release_id_override or settings.knowledge_active_release_id
    pointer_release_id = read_active_release_id(release_dir)
    release_id = explicit_release_id or pointer_release_id

    if release_id:
        resolved = _resolve_local_portal_release(
            settings,
            release_dir=release_dir,
            release_id=release_id,
            mode=mode,
        )
        if resolved is not None:
            return resolved

    if mode == "PORTAL":
        raise FileNotFoundError(
            "KNOWLEDGE_RELEASE_MODE=PORTAL requires an active portal release index."
        )

    bundled = settings.index_path
    if bundled.is_file():
        return ResolvedKnowledgeIndex(
            index_path=bundled,
            release_id=None,
            source="bundled_index",
        )

    if mode == "BUNDLED" or not settings.auto_build_index:
        raise FileNotFoundError(f"RAG index not found: {bundled}")

    return ResolvedKnowledgeIndex(
        index_path=bundled,
        release_id=None,
        source="auto_build",
    )


def _resolve_local_sandbox_under_gcs_store(
    settings: RagSettings,
    *,
    release_dir: Path,
    release_id_override: str | None,
    mode: str,
) -> ResolvedKnowledgeIndex:
    """LOCAL_SANDBOX may use the local sandbox tree; never silent bundled fallback."""
    explicit_release_id = release_id_override or settings.knowledge_active_release_id
    pointer_release_id = read_active_release_id(release_dir)
    release_id = explicit_release_id or pointer_release_id
    if not release_id:
        raise FileNotFoundError(
            "LOCAL_SANDBOX selection requires a sandbox release id "
            "(KNOWLEDGE_ACTIVE_RELEASE_ID or active_release.json)."
        )
    resolved = _resolve_local_portal_release(
        settings,
        release_dir=release_dir,
        release_id=release_id,
        mode="PORTAL",
    )
    if resolved is None:
        raise FileNotFoundError(
            f"LOCAL_SANDBOX knowledge release index not found for '{release_id}'."
        )
    return ResolvedKnowledgeIndex(
        index_path=resolved.index_path,
        release_id=resolved.release_id,
        source="local_sandbox",
        artifact=resolved.artifact,
        release_dir=resolved.release_dir,
        file_search_store=resolved.file_search_store,
    )


def _follow_cloud_target_release_id(
    *,
    release_id: str | None,
    sync_status: KnowledgeReleaseSyncStatus | None,
    cache_dir: Path,
    tenant_id: str,
) -> str | None:
    """Prefer a FOLLOW_CLOUD snapshot that is actually on disk.

    ``loadedReleaseId`` is a previous-process report, including LOCAL_SANDBOX
    ids that were persisted into the GCS status file. A missing loaded mirror
    must not hide the just-synced cloud snapshot.
    """
    loaded_id = sync_status.loaded_release_id if sync_status else None
    candidates: list[str] = []
    for candidate in (
        release_id,
        sync_status.mirrored_release_id if sync_status else None,
        sync_status.cloud_active_release_id if sync_status else None,
        loaded_id,
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        if (
            resolve_mirrored_release_dir(
                cache_dir,
                tenant_id=tenant_id,
                release_id=candidate,
            )
            is None
        ):
            continue
        if loaded_id and candidate != loaded_id:
            logger.info(
                "FOLLOW_CLOUD using mirrored release %s instead of missing loaded %s.",
                candidate,
                loaded_id,
            )
        return candidate
    return candidates[0] if candidates else None


def _resolve_gcs_mirrored_knowledge_index(
    settings: RagSettings,
    *,
    release_id: str | None,
    selection: KnowledgeReleaseSelectionMode,
) -> ResolvedKnowledgeIndex:
    """Load a previously synced local mirror. Never downloads on the Q&A path."""
    cache_dir = settings.knowledge_release_cache_dir or (
        settings.data_dir / "knowledge_cache"
    )
    tenant_id = settings.knowledge_release_tenant_id
    sync_status = read_sync_status(cache_dir, tenant_id)

    if selection is KnowledgeReleaseSelectionMode.PINNED:
        target_release_id = release_id
        if not target_release_id:
            raise FileNotFoundError(
                "PINNED selection requires KNOWLEDGE_ACTIVE_RELEASE_ID."
            )
    else:
        target_release_id = _follow_cloud_target_release_id(
            release_id=release_id,
            sync_status=sync_status,
            cache_dir=cache_dir,
            tenant_id=tenant_id,
        )

    if not target_release_id:
        raise FileNotFoundError(
            "No verified local knowledge snapshot is available for GCS mirror mode. "
            "Wait for the background syncer or run sync now."
        )

    mirrored = resolve_mirrored_release_dir(
        cache_dir,
        tenant_id=tenant_id,
        release_id=target_release_id,
    )
    if mirrored is None:
        raise FileNotFoundError(
            f"Local knowledge mirror for release '{target_release_id}' is missing."
        )

    releases_root = mirrored.parent
    release_root_for_validation = releases_root

    marker_ok = is_verified_qa_snapshot(mirrored)
    legacy_index_only = (mirrored / MANIFEST_FILENAME).is_file() and (
        mirrored / "index" / "chunks.json"
    ).is_file()
    if not marker_ok and not legacy_index_only:
        raise FileNotFoundError(
            f"Local knowledge mirror for release '{target_release_id}' is not verified."
        )

    artifact = validate_release_artifacts(
        release_root_for_validation,
        target_release_id,
        require_vectors=settings.knowledge_release_require_vectors,
        expected_tenant_id=tenant_id,
        expected_purpose=None,
    )
    index_path = mirrored / "index" / "chunks.json"
    source = "gcs_mirror" if marker_ok else "gcs_mirror_index_only"
    if source == "gcs_mirror_index_only":
        logger.warning(
            "Loading index-only GCS mirror for %s; runtimeArtifacts inventory absent.",
            target_release_id,
        )
    return ResolvedKnowledgeIndex(
        index_path=index_path,
        release_id=target_release_id,
        source=source,
        artifact=artifact,
        release_dir=release_root_for_validation,
        file_search_store=manifest_file_search_store(mirrored),
    )


def manifest_file_search_store(release_dir: Path) -> str | None:
    manifest_path = release_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    backends = payload.get("backends")
    if not isinstance(backends, dict):
        return None
    file_search = backends.get("geminiFileSearch")
    if not isinstance(file_search, dict) or not file_search.get("ready"):
        return None
    store = str(file_search.get("store") or "").strip()
    return store or None
