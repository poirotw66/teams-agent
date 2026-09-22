"""Active-pointer knowledge-index reload helpers for FastAPI app state."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI

from .graph import RagAgent
from .knowledge_backends import KnowledgeBackendRouter
from .knowledge_release import manifest_file_search_store, resolve_knowledge_index
from .knowledge_release_sync import (
    KnowledgeReleaseSelectionMode,
    resolve_selection_mode,
)
from .release_artifacts import MANIFEST_FILENAME, KnowledgeIndexArtifact, validate_release_artifacts
from .retrieval import HybridIndex
from .service_scope_evidence import configure_service_scope_from_release
from .settings import RagSettings
from .source_refs import hydrate_index_sources
from .workflow import build_knowledge_service

logger = logging.getLogger(__name__)


def load_validated_release_index(
    *,
    target_app: FastAPI,
    resolved_settings: RagSettings,
    release_dir: Path,
    active_release_id: str,
    target_index_path: Path,
) -> tuple[HybridIndex, KnowledgeIndexArtifact | None]:
    """Load and hydrate the hybrid index for an active portal release."""
    release_path = target_index_path.parents[1]
    artifact = None
    if (
        (release_path / MANIFEST_FILENAME).is_file()
        or resolved_settings.knowledge_release_require_manifest
        or resolved_settings.knowledge_release_require_vectors
    ):
        artifact = validate_release_artifacts(
            release_dir,
            active_release_id,
            require_vectors=resolved_settings.knowledge_release_require_vectors,
        )
    from .model_control import embedding_model_for_load
    from .retrieval import hybrid_index_fusion_kwargs

    new_index = HybridIndex.load(
        target_index_path,
        embedding_model_for_load(target_app, resolved_settings),
        **hybrid_index_fusion_kwargs(resolved_settings),
    )
    hydrate_index_sources(
        new_index.chunks,
        release_dir=release_dir,
        release_id=active_release_id,
    )
    return new_index, artifact


def apply_synced_knowledge_index(
    *,
    target_app: FastAPI,
    resolved_settings: RagSettings,
    new_index: HybridIndex,
    target_index_path: Path,
    active_release_id: str,
    artifact: KnowledgeIndexArtifact | None,
    source: str = "portal_release",
    release_root: Path | None = None,
) -> None:
    """Wire a freshly loaded index into app state and the knowledge router."""
    new_agent = RagAgent(resolved_settings, new_index)
    new_hybrid_service = build_knowledge_service(
        target_app.state.hybrid_settings,
        new_index,
        target_app.state.rag_model,
        release_id=active_release_id,
    )
    router: KnowledgeBackendRouter = target_app.state.knowledge_router
    router.update_service("HYBRID", new_hybrid_service)
    release_path = target_index_path.parents[1]
    file_search_store = manifest_file_search_store(release_path)
    if file_search_store:
        file_search_settings = replace(
            resolved_settings,
            knowledge_service_mode="GEMINI_FILE_SEARCH",
            gemini_file_search_store=file_search_store,
        )
        router.update_service(
            "GEMINI_FILE_SEARCH",
            build_knowledge_service(
                file_search_settings,
                new_index,
                target_app.state.rag_model,
                release_id=active_release_id,
            ),
        )
    else:
        router.remove_service(
            "GEMINI_FILE_SEARCH",
            "此知識版本沒有通過驗證的 Gemini File Search 綁定。",
        )

    target_app.state.index = new_index
    target_app.state.knowledge_index_path = target_index_path
    target_app.state.knowledge_release_id = active_release_id
    target_app.state.knowledge_index_source = source
    target_app.state.knowledge_index_artifact = artifact
    target_app.state.agent = new_agent
    scope_root = release_root or resolved_settings.knowledge_release_dir or (
        resolved_settings.data_dir / "releases"
    )
    configure_service_scope_from_release(scope_root, active_release_id)
    syncer = getattr(target_app.state, "knowledge_release_syncer", None)
    if syncer is not None:
        syncer.set_loaded_release_id(active_release_id)
    logger.info(
        "Auto-synced knowledge index to active pointer: release_id=%s chunks=%d",
        active_release_id,
        len(new_index.chunks),
    )


def apply_follow_cloud_mirror_reload(
    target_app: FastAPI,
    resolved_settings: RagSettings,
    *,
    release_id: str,
    release_dir: Path | None = None,
) -> bool:
    """Hot-swap the Agent to a verified local GCS mirror (FOLLOW_CLOUD only).

    Returns True when the in-memory index was switched. PINNED / LOCAL_SANDBOX
    selection modes refuse the swap so sync never overrides the test pin.
    """
    del release_dir  # Path is resolved from the verified cache via settings.
    selection = resolve_selection_mode(resolved_settings)
    if selection is not KnowledgeReleaseSelectionMode.FOLLOW_CLOUD:
        logger.info(
            "Skipping FOLLOW_CLOUD reload for selection_mode=%s release_id=%s",
            selection.value,
            release_id,
        )
        return False
    current = getattr(target_app.state, "knowledge_release_id", None)
    if current == release_id:
        syncer = getattr(target_app.state, "knowledge_release_syncer", None)
        if syncer is not None:
            syncer.set_loaded_release_id(release_id)
        return False
    try:
        resolved = resolve_knowledge_index(
            resolved_settings,
            release_id_override=release_id,
        )
    except (FileNotFoundError, ValueError) as error:
        logger.error(
            "FOLLOW_CLOUD reload failed to resolve mirror %s: %s",
            release_id,
            error,
        )
        return False
    if resolved.release_id != release_id or resolved.release_dir is None:
        logger.error(
            "FOLLOW_CLOUD reload resolved unexpected release: wanted=%s got=%s",
            release_id,
            resolved.release_id,
        )
        return False
    new_index, artifact = load_validated_release_index(
        target_app=target_app,
        resolved_settings=resolved_settings,
        release_dir=resolved.release_dir,
        active_release_id=release_id,
        target_index_path=resolved.index_path,
    )
    apply_synced_knowledge_index(
        target_app=target_app,
        resolved_settings=resolved_settings,
        new_index=new_index,
        target_index_path=resolved.index_path,
        active_release_id=release_id,
        artifact=artifact or resolved.artifact,
        source=resolved.source,
        release_root=resolved.release_dir,
    )
    return True


__all__ = [
    "apply_follow_cloud_mirror_reload",
    "apply_synced_knowledge_index",
    "load_validated_release_index",
]
