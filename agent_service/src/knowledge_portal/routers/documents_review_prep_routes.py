"""Document start-revision / evaluate / validate routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_core.chunking_profile import ChunkingProfile
from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_review_prep_routes(
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
    del settings, pdf_job_store, idempotency_key

    @app.post("/api/documents/{document_id}/start-revision")
    async def start_revision(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.start_revision(actor, document_id, correlation_id_value)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/evaluate")
    @app.post("/api/v1/documents/{document_id}/evaluate")
    async def evaluate_document_candidate(
        document_id: str,
        profile: ChunkingProfile = ChunkingProfile.AUTO,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            preview = await service.preview_chunks(actor, document_id, profile=profile)
            quality = preview["quality"]
            return {
                "documentId": document_id,
                "versionId": preview["versionId"],
                "profile": preview["profile"],
                "ready": bool(quality["acceptable"]),
                "quality": quality,
            }
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/validate")
    async def validate_document(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.validate_document(actor, document_id)
        except Exception as exc:
            raise handle_errors(exc) from exc
