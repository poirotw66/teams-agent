"""Knowledge Portal documents and ingestion HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
)

from knowledge_core.chunking_profile import ChunkingProfile
from knowledge_portal.models import (
    CreateDocumentRequest,
    PortalActor,
    PublishRequest,
    RemoveDocumentRequest,
    SubmitReviewRequest,
    UpdateDraftRequest,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_routes(
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
    @app.get("/api/documents")
    async def list_documents(
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
        format: str | None = None,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.list_documents(
            actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
            format=format,
        )

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

    @app.post("/api/documents")
    async def create_document(
        request: CreateDocumentRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
        idempotency_key_value: str | None = Depends(idempotency_key),
    ):
        try:
            return await service.create_document(
                actor,
                request,
                correlation_id_value,
                idempotency_key=idempotency_key_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/{document_id}")
    async def get_document(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.get_document(actor, document_id)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/{document_id}/chunk-preview")
    @app.get("/api/v1/documents/{document_id}/chunk-preview")
    async def preview_document_chunks(
        document_id: str,
        profile: ChunkingProfile = ChunkingProfile.AUTO,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.preview_chunks(
                actor,
                document_id,
                profile=profile,
            )
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

    @app.post("/api/documents/{document_id}/discard-draft")
    async def discard_draft(
        document_id: str,
        request: RemoveDocumentRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.discard_draft(
                actor,
                document_id,
                request,
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/unpublish")
    async def unpublish_document(
        document_id: str,
        request: RemoveDocumentRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.unpublish_document(
                actor,
                document_id,
                request,
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.delete("/api/documents/{document_id}")
    async def remove_document(
        document_id: str,
        reason: str = "Removed from the knowledge library.",
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.remove_document(
                actor,
                document_id,
                RemoveDocumentRequest(reason=reason),
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.put("/api/documents/{document_id}/draft")
    async def update_draft(
        document_id: str,
        request: UpdateDraftRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.update_draft(actor, document_id, request, correlation_id_value)
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

    @app.post("/api/documents/{document_id}/submit-review")
    async def submit_review(
        document_id: str,
        request: SubmitReviewRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.submit_for_review(
                actor, document_id, request, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/publish")
    async def publish_document(
        document_id: str,
        request: PublishRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
        idempotency_key_value: str | None = Depends(idempotency_key),
    ):
        try:
            return await service.publish_version(
                actor,
                document_id,
                request,
                correlation_id_value,
                idempotency_key=idempotency_key_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

