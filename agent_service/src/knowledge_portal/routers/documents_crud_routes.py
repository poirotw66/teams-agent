"""Document list/create/get/draft CRUD routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_portal.models import (
    CreateDocumentRequest,
    PortalActor,
    UpdateDraftRequest,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_crud_routes(
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
    del settings, pdf_job_store

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
