"""Example create routes for FAQ and manual sources."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header

from ..request_models import ExampleCreateRequest
from .example_create_call import create_example_from_payload
from .example_create_sources import resolve_faq_example_source


def register_example_faq_manual_create_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    example_service,
    faq_service,
    current_actor,
    require_capability,
) -> None:
    del query_service

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/examples")
    async def create_faq_example(
        faq_id: str,
        version_id: str,
        payload: ExampleCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        faq = faq_service.detail(faq_id=faq_id, actor=actor)
        source_version = resolve_faq_example_source(faq, version_id)
        return create_example_from_payload(
            example_service,
            source_type="FAQ",
            source_id=faq_id,
            source_version_id=version_id,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=source_version["content"]["owner_unit_id"],
            payload=payload,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/examples/manual")
    async def create_manual_example(
        payload: ExampleCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        return create_example_from_payload(
            example_service,
            source_type="MANUAL",
            source_id=f"manual:{actor.user_id}",
            source_version_id=None,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=resolved_settings.default_owner_unit_id,
            payload=payload,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
