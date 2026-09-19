"""Active-pointer knowledge-index reload helpers for FastAPI app state."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI

from .graph import RagAgent
from .knowledge_backends import KnowledgeBackendRouter
from .knowledge_release import manifest_file_search_store
from .release_artifacts import MANIFEST_FILENAME, KnowledgeIndexArtifact, validate_release_artifacts
from .retrieval import HybridIndex
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
    target_app.state.knowledge_index_source = "portal_release"
    target_app.state.knowledge_index_artifact = artifact
    target_app.state.agent = new_agent
    logger.info(
        "Auto-synced knowledge index to active pointer: release_id=%s chunks=%d",
        active_release_id,
        len(new_index.chunks),
    )


__all__ = ["apply_synced_knowledge_index", "load_validated_release_index"]
