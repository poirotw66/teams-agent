"""Example create routes for document and conversation sources."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header

from ..request_models import ExampleCreateRequest
from .example_create_call import create_example_from_payload
from .example_create_sources import (
    resolve_conversation_example_source,
    resolve_document_example_source,
)


def register_example_doc_conversation_create_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    example_service,
    faq_service,
    current_actor,
    require_capability,
) -> None:
    del resolved_settings, faq_service

    @app.post("/api/knowledge/{document_id}/versions/{version_id}/examples")
    async def create_document_example(
        document_id: str,
        version_id: str,
        payload: ExampleCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        owner_unit_id = await resolve_document_example_source(
            query_service, actor, document_id, version_id
        )
        return create_example_from_payload(
            example_service,
            source_type="DOCUMENT",
            source_id=document_id,
            source_version_id=version_id,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=owner_unit_id,
            payload=payload,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/conversations/{conversation_id}/examples")
    async def create_conversation_example(
        conversation_id: str,
        payload: ExampleCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        owner_unit_id, source_correlation_id = await resolve_conversation_example_source(
            query_service, actor, conversation_id
        )
        return create_example_from_payload(
            example_service,
            source_type="CONVERSATION",
            source_id=conversation_id,
            source_version_id=None,
            source_correlation_id=source_correlation_id,
            owner_unit_id=owner_unit_id,
            payload=payload,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
