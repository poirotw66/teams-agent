"""Admin knowledge-backend and release-reload routes."""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request

from ..contracts import KnowledgeBackendUpdate, ReloadKnowledgeRequest
from ..deps import sync_knowledge_to_active_pointer
from ..graph import RagAgent
from ..knowledge_backends import KnowledgeBackendRouter
from ..knowledge_release import (
    read_active_release_id,
    release_index_path,
    resolve_knowledge_index,
)
from ..retrieval import HybridIndex
from ..settings import RagSettings
from ..workflow import build_knowledge_service

logger = logging.getLogger(__name__)


def register_knowledge_admin_routes(
    app: FastAPI,
    *,
    resolved_settings: RagSettings,
    authorize: Callable[..., None],
) -> None:
    @app.get(
        "/admin/knowledge-backend",
        dependencies=[Depends(authorize)],
    )
    async def get_knowledge_backend(request: Request) -> dict[str, object]:
        router: KnowledgeBackendRouter = request.app.state.knowledge_router
        return await router.status()

    @app.put(
        "/admin/knowledge-backend",
        dependencies=[Depends(authorize)],
    )
    async def set_knowledge_backend(
        payload: KnowledgeBackendUpdate, request: Request
    ) -> dict[str, object]:
        if not resolved_settings.knowledge_backend_admin_enabled:
            raise HTTPException(
                status_code=403,
                detail="Knowledge backend switching is disabled in this environment.",
            )
        router: KnowledgeBackendRouter = request.app.state.knowledge_router
        try:
            await router.select(payload.backend)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        logger.info("Knowledge backend changed: backend=%s", payload.backend)
        return await router.status()

    @app.get(
        "/admin/knowledge-status",
        dependencies=[Depends(authorize)],
    )
    async def get_knowledge_status(request: Request) -> dict[str, object]:
        sync_knowledge_to_active_pointer(request.app, resolved_settings)
        release_dir = (
            resolved_settings.knowledge_release_dir
            or (resolved_settings.data_dir / "releases")
        )
        active_id = read_active_release_id(release_dir)
        current_id = getattr(request.app.state, "knowledge_release_id", None)
        index: HybridIndex | None = getattr(request.app.state, "index", None)
        return {
            "currentReleaseId": current_id,
            "targetReleaseId": active_id,
            "inSync": current_id == active_id if active_id else True,
            "chunks": len(index.chunks) if index else 0,
            "source": getattr(request.app.state, "knowledge_index_source", "bundled_index"),
            "indexPath": str(
                getattr(request.app.state, "knowledge_index_path", resolved_settings.index_path)
            ),
        }

    @app.post(
        "/admin/reload-knowledge",
        dependencies=[Depends(authorize)],
    )
    async def reload_knowledge(
        request: Request,
        payload: ReloadKnowledgeRequest | None = None,
    ) -> dict[str, object]:
        target_release_id: str | None = None
        release_dir = (
            resolved_settings.knowledge_release_dir
            or (resolved_settings.data_dir / "releases")
        )
        active_release_id = read_active_release_id(release_dir)
        requested_release_id = payload.target_release_id if payload else None

        if requested_release_id:
            if active_release_id and requested_release_id != active_release_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Stale deployment request: target release '{requested_release_id}' "
                        f"does not match active release '{active_release_id}'."
                    ),
                )
            target_release_id = requested_release_id
            target_index_path = release_index_path(release_dir, target_release_id)
            source = "portal_release"
        elif active_release_id:
            target_release_id = active_release_id
            target_index_path = release_index_path(release_dir, target_release_id)
            source = "portal_release"
        else:
            resolved_index = resolve_knowledge_index(resolved_settings)
            target_release_id = resolved_index.release_id
            target_index_path = resolved_index.index_path
            source = resolved_index.source

        if not target_index_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Knowledge index not found: {target_index_path}",
            )

        new_index = HybridIndex.load(
            target_index_path,
            resolved_settings.embedding_model,
        )
        new_agent = RagAgent(resolved_settings, new_index)
        new_hybrid_service = build_knowledge_service(
            request.app.state.hybrid_settings,
            new_index,
            request.app.state.rag_model,
        )
        router: KnowledgeBackendRouter = request.app.state.knowledge_router
        router.update_service("HYBRID", new_hybrid_service)

        request.app.state.index = new_index
        request.app.state.knowledge_index_path = target_index_path
        request.app.state.knowledge_release_id = target_release_id
        request.app.state.knowledge_index_source = source
        request.app.state.agent = new_agent

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
