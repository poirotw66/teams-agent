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

from .knowledge_release_control import read_firestore_release_reference
from .knowledge_release_gcs import download_release_metadata
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
        return _resolve_gcs_knowledge_index(
            settings,
            release_id=release_id_override or settings.knowledge_active_release_id,
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


def _resolve_gcs_knowledge_index(
    settings: RagSettings,
    *,
    release_id: str | None,
) -> ResolvedKnowledgeIndex:
    reference = read_firestore_release_reference(settings, release_id=release_id)
    cache_dir = settings.knowledge_release_cache_dir or (
        settings.data_dir / "knowledge_cache"
    )
    index_path = download_release_metadata(
        cache_dir,
        bucket_name=reference.bucket,
        object_prefix=settings.knowledge_release_gcs_prefix,
        tenant_id=reference.tenant_id,
        release_id=reference.release_id,
        manifest_generation=reference.manifest_generation,
        index_generation=reference.index_generation,
    )
    artifact = validate_release_artifacts(
        cache_dir,
        reference.release_id,
        require_vectors=settings.knowledge_release_require_vectors,
        expected_tenant_id=reference.tenant_id,
        expected_purpose=reference.purpose,
    )
    expected_metadata = {
        "sha256": reference.index_sha256,
        "chunk_count": reference.chunk_count,
        "vector_count": reference.vector_count,
        "embedding_model": reference.embedding_model,
        "embedding_dimensions": reference.embedding_dimensions,
    }
    actual_metadata = {
        "sha256": artifact.sha256,
        "chunk_count": artifact.chunk_count,
        "vector_count": artifact.vector_count,
        "embedding_model": artifact.embedding_model,
        "embedding_dimensions": artifact.embedding_dimensions,
    }
    if actual_metadata != expected_metadata:
        raise ValueError(
            "Downloaded knowledge index does not match its Firestore release record."
        )
    return ResolvedKnowledgeIndex(
        index_path=index_path,
        release_id=reference.release_id,
        source="gcs_release",
        artifact=artifact,
        release_dir=cache_dir,
        file_search_store=manifest_file_search_store(index_path.parents[1]),
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
