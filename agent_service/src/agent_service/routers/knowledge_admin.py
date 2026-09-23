"""Admin knowledge-backend and release-reload routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request

from ..contracts import KnowledgeBackendUpdate, ReloadKnowledgeRequest
from ..deps import sync_knowledge_to_active_pointer
from ..knowledge_backends import KnowledgeBackendRouter
from ..knowledge_mirror_inventory import (
    MirrorDocumentNotFound,
    attach_mirror_documents,
    preview_mirrored_document,
)
from ..knowledge_release import read_active_release_id
from ..knowledge_release_control import FirestoreKnowledgeReleaseControl
from ..retrieval import HybridIndex
from ..settings import RagSettings
from .knowledge_admin_reload import perform_knowledge_reload

logger = logging.getLogger(__name__)


def _is_aligned_with_cloud(
    sync_status: dict[str, object],
    loaded_id: object,
) -> bool:
    selection_mode = str(sync_status.get("selectionMode") or "").upper()
    return bool(
        selection_mode == "FOLLOW_CLOUD"
        and sync_status.get("runtimeInventoryComplete")
        and sync_status.get("syncState") == "IN_SYNC"
        and sync_status.get("cloudActiveReleaseId")
        and sync_status.get("cloudActiveReleaseId")
        == sync_status.get("mirroredReleaseId")
        == loaded_id
        and not sync_status.get("behindCloud")
    )


def _public_sync_with_loaded_release(
    sync_status: dict[str, object],
    *,
    loaded_id: object,
    settings: RagSettings,
) -> dict[str, object]:
    aligned = _is_aligned_with_cloud(sync_status, loaded_id)
    return attach_mirror_documents(
        {
            **sync_status,
            "loadedReleaseId": loaded_id,
            "alignedWithCloud": aligned,
            "matchesCloudProduction": aligned,
        },
        settings=settings,
        release_id=str(loaded_id) if loaded_id else None,
    )


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
        sync_status = _public_sync_with_loaded_release(
            sync_status,
            loaded_id=current_id,
            settings=resolved_settings,
        )
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


async def _sync_gcs_knowledge_release(
    request: Request,
    resolved_settings: RagSettings,
) -> dict[str, object]:
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
    loaded_id = getattr(request.app.state, "knowledge_release_id", None)
    return _public_sync_with_loaded_release(
        status.to_public_dict(),
        loaded_id=loaded_id,
        settings=resolved_settings,
    )


async def _preview_knowledge_mirror_document(
    document_id: str,
    request: Request,
    resolved_settings: RagSettings,
) -> dict[str, object]:
    loaded_id = getattr(request.app.state, "knowledge_release_id", None)
    try:
        return await asyncio.to_thread(
            preview_mirrored_document,
            settings=resolved_settings,
            release_id=str(loaded_id) if loaded_id else None,
            document_id=document_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except MirrorDocumentNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
        return await _sync_gcs_knowledge_release(request, resolved_settings)

    @app.get(
        "/admin/knowledge-mirror-documents/{document_id}",
        dependencies=[Depends(authorize)],
    )
    async def get_knowledge_mirror_document(
        document_id: str,
        request: Request,
    ) -> dict[str, object]:
        return await _preview_knowledge_mirror_document(
            document_id,
            request,
            resolved_settings,
        )

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
