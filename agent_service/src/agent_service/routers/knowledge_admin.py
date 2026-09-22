"""Admin knowledge-backend and release-reload routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request

from ..contracts import KnowledgeBackendUpdate, ReloadKnowledgeRequest
from ..deps import sync_knowledge_to_active_pointer
from ..knowledge_backends import KnowledgeBackendRouter
from ..knowledge_release import read_active_release_id
from ..knowledge_release_control import FirestoreKnowledgeReleaseControl
from ..retrieval import HybridIndex
from ..settings import RagSettings
from .knowledge_admin_reload import perform_knowledge_reload

logger = logging.getLogger(__name__)


async def _build_knowledge_status(
    request: Request,
    resolved_settings: RagSettings,
) -> dict[str, object]:
    release_dir = resolved_settings.knowledge_release_dir or (
        resolved_settings.data_dir / "releases"
    )
    sync_status: dict[str, object] | None = None
    if resolved_settings.knowledge_release_store_mode == "GCS":
        syncer = getattr(request.app.state, "knowledge_release_syncer", None)
        if syncer is not None:
            sync_status = syncer.status.to_public_dict()
            active_id = syncer.status.cloud_active_release_id
        else:
            control: FirestoreKnowledgeReleaseControl | None = getattr(
                request.app.state,
                "knowledge_release_control",
                None,
            )
            if control is None:
                raise HTTPException(
                    status_code=503,
                    detail="Knowledge release control plane is unavailable.",
                )
            try:
                active_id = await asyncio.to_thread(control.read_active_release_id)
            except Exception as error:
                raise HTTPException(
                    status_code=503,
                    detail="Knowledge release control plane is unavailable.",
                ) from error
    else:
        sync_knowledge_to_active_pointer(request.app, resolved_settings)
        active_id = read_active_release_id(release_dir)
    current_id = getattr(request.app.state, "knowledge_release_id", None)
    index: HybridIndex | None = getattr(request.app.state, "index", None)
    if sync_status is not None:
        # Always report the Agent's actual loaded release, not a desired target.
        selection_mode = str(sync_status.get("selectionMode") or "").upper()
        can_claim_cloud = selection_mode == "FOLLOW_CLOUD"
        aligned = bool(
            can_claim_cloud
            and sync_status.get("runtimeInventoryComplete")
            and sync_status.get("syncState") == "IN_SYNC"
            and sync_status.get("cloudActiveReleaseId")
            and sync_status.get("cloudActiveReleaseId")
            == sync_status.get("mirroredReleaseId")
            == current_id
            and not sync_status.get("behindCloud")
        )
        sync_status = {
            **sync_status,
            "loadedReleaseId": current_id,
            "alignedWithCloud": aligned,
            "matchesCloudProduction": aligned,
        }
        syncer = getattr(request.app.state, "knowledge_release_syncer", None)
        if syncer is not None and current_id != syncer.status.loaded_release_id:
            syncer.set_loaded_release_id(current_id)
    payload: dict[str, object] = {
        "currentReleaseId": current_id,
        "targetReleaseId": active_id,
        "inSync": current_id == active_id if active_id else True,
        "chunks": len(index.chunks) if index else 0,
        "source": getattr(request.app.state, "knowledge_index_source", "bundled_index"),
        "indexPath": str(
            getattr(request.app.state, "knowledge_index_path", resolved_settings.index_path)
        ),
    }
    if sync_status is not None:
        payload["sync"] = sync_status
    return payload


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
        return await _build_knowledge_status(request, resolved_settings)

    @app.post(
        "/admin/knowledge-sync",
        dependencies=[Depends(authorize)],
    )
    async def sync_knowledge_release(request: Request) -> dict[str, object]:
        if resolved_settings.knowledge_release_store_mode != "GCS":
            raise HTTPException(
                status_code=409,
                detail="Knowledge sync is only available when KNOWLEDGE_RELEASE_STORE_MODE=GCS.",
            )
        syncer = getattr(request.app.state, "knowledge_release_syncer", None)
        if syncer is None:
            raise HTTPException(
                status_code=503,
                detail="Knowledge release syncer is unavailable.",
            )
        status = await asyncio.to_thread(syncer.sync_now)
        # FOLLOW_CLOUD hot-reload runs via syncer callback when wired; also
        # ensure status reflects the Agent's actual loaded release id.
        loaded_id = getattr(request.app.state, "knowledge_release_id", None)
        public = status.to_public_dict()
        public["loadedReleaseId"] = loaded_id
        selection_mode = str(public.get("selectionMode") or "").upper()
        can_claim_cloud = selection_mode == "FOLLOW_CLOUD"
        aligned = bool(
            can_claim_cloud
            and public.get("runtimeInventoryComplete")
            and public.get("syncState") == "IN_SYNC"
            and public.get("cloudActiveReleaseId")
            and public.get("cloudActiveReleaseId")
            == public.get("mirroredReleaseId")
            == loaded_id
            and not public.get("behindCloud")
        )
        public["alignedWithCloud"] = aligned
        public["matchesCloudProduction"] = aligned
        return public

    @app.post(
        "/admin/reload-knowledge",
        dependencies=[Depends(authorize)],
    )
    async def reload_knowledge(
        request: Request,
        payload: ReloadKnowledgeRequest | None = None,
    ) -> dict[str, object]:
        return await perform_knowledge_reload(
            request,
            resolved_settings=resolved_settings,
            payload=payload,
        )
