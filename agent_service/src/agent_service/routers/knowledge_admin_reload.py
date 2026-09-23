"""Knowledge index reload implementation for admin routes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

from fastapi import HTTPException, Request

from ..contracts import ReloadKnowledgeRequest
from ..graph import RagAgent
from ..knowledge_backends import KnowledgeBackendRouter
from ..knowledge_release import (
    manifest_file_search_store,
    read_active_release_id,
    release_index_path,
    resolve_knowledge_index,
)
from ..model_control import embedding_model_for_load
from ..retrieval import HybridIndex, hybrid_index_fusion_kwargs
from ..service_scope_evidence import (
    configure_service_scope_from_release,
    reset_service_scope_catalog,
)
from ..settings import RagSettings
from ..source_refs import hydrate_index_sources
from ..workflow import build_knowledge_service

logger = logging.getLogger(__name__)


def _sync_gcs_mirror_before_reload(request: Request) -> None:
    """Pull the cloud-active QA snapshot before resolving a GCS mirror load.

    Portal activation notifies ``/admin/reload-knowledge`` immediately after
    advancing the Firestore active pointer. Without a sync first, FOLLOW_CLOUD
    Agents reject the new release with HTTP 409 (mirror missing) and Portal
    compensates back to the previous active release — leaving newly published
    documents invisible to Playground while Console still reports IN_SYNC with
    the older cloud-active id.
    """
    syncer = getattr(request.app.state, "knowledge_release_syncer", None)
    if syncer is None:
        return
    status = syncer.sync_now()
    logger.info(
        "GCS mirror sync before reload: cloud=%s mirrored=%s state=%s",
        status.cloud_active_release_id,
        status.mirrored_release_id,
        status.sync_state.value if hasattr(status.sync_state, "value") else status.sync_state,
    )


def _resolve_reload_target(
    resolved_settings: RagSettings,
    *,
    release_dir: Path,
    requested_release_id: str | None,
    active_release_id: str | None,
) -> tuple[str | None, Path, str, object | None, str | None]:
    if resolved_settings.knowledge_release_store_mode == "GCS":
        try:
            resolved_index = resolve_knowledge_index(
                resolved_settings,
                release_id_override=requested_release_id,
            )
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return (
            resolved_index.release_id,
            resolved_index.index_path,
            resolved_index.source,
            resolved_index.artifact,
            resolved_index.file_search_store,
        )

    if requested_release_id:
        if active_release_id and requested_release_id != active_release_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Stale deployment request: target release '{requested_release_id}' "
                    f"does not match active release '{active_release_id}'."
                ),
            )
        resolved_index = resolve_knowledge_index(
            resolved_settings,
            release_id_override=requested_release_id,
        )
        if resolved_index.release_id != requested_release_id:
            raise HTTPException(
                status_code=404,
                detail=f"Knowledge release not found: {requested_release_id}",
            )
        return (
            resolved_index.release_id,
            resolved_index.index_path,
            resolved_index.source,
            resolved_index.artifact,
            resolved_index.file_search_store,
        )

    if active_release_id:
        target_index_path = release_index_path(release_dir, active_release_id)
        return (
            active_release_id,
            target_index_path,
            "portal_release",
            None,
            manifest_file_search_store(target_index_path.parents[1]),
        )

    resolved_index = resolve_knowledge_index(resolved_settings)
    return (
        resolved_index.release_id,
        resolved_index.index_path,
        resolved_index.source,
        resolved_index.artifact,
        resolved_index.file_search_store,
    )


def _apply_reloaded_services(
    request: Request,
    *,
    resolved_settings: RagSettings,
    new_index: HybridIndex,
    target_release_id: str | None,
    resolved_file_search_store: str | None,
) -> None:
    new_hybrid_service = build_knowledge_service(
        request.app.state.hybrid_settings,
        new_index,
        request.app.state.rag_model,
        release_id=target_release_id,
    )
    router: KnowledgeBackendRouter = request.app.state.knowledge_router
    router.update_service("HYBRID", new_hybrid_service)
    if resolved_file_search_store:
        file_search_settings = replace(
            resolved_settings,
            knowledge_service_mode="GEMINI_FILE_SEARCH",
            gemini_file_search_store=resolved_file_search_store,
        )
        router.update_service(
            "GEMINI_FILE_SEARCH",
            build_knowledge_service(
                file_search_settings,
                new_index,
                request.app.state.rag_model,
                release_id=target_release_id,
            ),
        )
    elif target_release_id:
        router.remove_service(
            "GEMINI_FILE_SEARCH",
            "此知識版本沒有通過驗證的 Gemini File Search 綁定。",
        )


async def perform_knowledge_reload(
    request: Request,
    *,
    resolved_settings: RagSettings,
    payload: ReloadKnowledgeRequest | None,
) -> dict[str, object]:
    release_dir = resolved_settings.knowledge_release_dir or (
        resolved_settings.data_dir / "releases"
    )
    active_release_id = read_active_release_id(release_dir)
    requested_release_id = payload.target_release_id if payload else None

    if resolved_settings.knowledge_release_store_mode == "GCS":
        await asyncio.to_thread(_sync_gcs_mirror_before_reload, request)

    (
        target_release_id,
        target_index_path,
        source,
        resolved_artifact,
        resolved_file_search_store,
    ) = _resolve_reload_target(
        resolved_settings,
        release_dir=release_dir,
        requested_release_id=requested_release_id,
        active_release_id=active_release_id,
    )

    if not target_index_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge index not found: {target_index_path}",
        )

    new_index = HybridIndex.load(
        target_index_path,
        embedding_model_for_load(request.app, resolved_settings),
        **hybrid_index_fusion_kwargs(resolved_settings),
    )
    hydrate_root = release_dir
    if resolved_settings.knowledge_release_store_mode == "GCS":
        # Mirror layout: index lives under <releases_root>/<releaseId>/index/...
        hydrate_root = target_index_path.parents[1].parent
    hydrate_index_sources(
        new_index.chunks,
        release_dir=hydrate_root,
        release_id=target_release_id,
    )
    new_agent = RagAgent(resolved_settings, new_index)
    _apply_reloaded_services(
        request,
        resolved_settings=resolved_settings,
        new_index=new_index,
        target_release_id=target_release_id,
        resolved_file_search_store=resolved_file_search_store,
    )

    request.app.state.index = new_index
    request.app.state.knowledge_index_path = target_index_path
    request.app.state.knowledge_release_id = target_release_id
    request.app.state.knowledge_index_source = source
    request.app.state.knowledge_index_artifact = resolved_artifact
    request.app.state.agent = new_agent

    if target_release_id:
        configure_service_scope_from_release(hydrate_root, target_release_id)
    else:
        reset_service_scope_catalog()

    syncer = getattr(request.app.state, "knowledge_release_syncer", None)
    if syncer is not None:
        syncer.set_loaded_release_id(target_release_id)

    logger.info(
        "Knowledge index reloaded: release_id=%s path=%s chunks=%d source=%s",
        target_release_id,
        target_index_path,
        len(new_index.chunks),
        source,
    )
    return {
        "status": "reloaded",
        "releaseId": target_release_id,
        "indexPath": str(target_index_path),
        "chunks": len(new_index.chunks),
        "source": source,
    }
