"""Document discard / unpublish / remove routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_portal.models import PortalActor, RemoveDocumentRequest
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_removal_routes(
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
