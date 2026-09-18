"""Document submit-review / publish routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_portal.models import PortalActor, PublishRequest, SubmitReviewRequest
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_publish_routes(
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
