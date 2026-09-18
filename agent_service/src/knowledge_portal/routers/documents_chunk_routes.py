"""Document chunk preview / rechunk routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_core.chunking_profile import ChunkingProfile
from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_chunk_routes(
    app: FastAPI,
    *,
    settings: PortalSettings,
    service: PortalService,
    pdf_job_store: Any,
    authorize: Callable[..., None],
    current_actor: Callable[..., PortalActor],
    correlation_id: Callable[..., str],
    idempotency_key: Callable[..., str | None],
    handle_errors: Callable[[Exception], HTTPException],
) -> None:
    del settings, pdf_job_store, correlation_id, idempotency_key

    @app.get("/api/documents/{document_id}/chunk-preview")
    @app.get("/api/v1/documents/{document_id}/chunk-preview")
    async def preview_document_chunks(
        document_id: str,
        profile: ChunkingProfile = ChunkingProfile.AUTO,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.preview_chunks(actor, document_id, profile=profile)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/v1/documents/{document_id}/versions/{version_id}/chunk-preview")
    async def preview_document_version_chunks(
        document_id: str,
        version_id: str,
        profile: ChunkingProfile = ChunkingProfile.AUTO,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.preview_chunks(
                actor,
                document_id,
                profile=profile,
                version_id=version_id,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/rechunk")
    @app.post("/api/v1/documents/{document_id}/rechunk")
    async def rechunk_document(
        document_id: str,
        profile: ChunkingProfile = ChunkingProfile.AUTO,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.preview_chunks(actor, document_id, profile=profile)
        except Exception as exc:
            raise handle_errors(exc) from exc
