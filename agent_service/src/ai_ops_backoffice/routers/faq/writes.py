"""FAQ create, edit, and test write routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header

from ...request_models import FaqCreateRequest, FaqEditRequest, FaqTestCreateRequest
from .context import FaqRouteContext


def register_faq_write_routes(app: FastAPI, ctx: FaqRouteContext) -> None:
    faq_service = ctx.faq_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @app.post("/api/faqs")
    async def create_faq(
        payload: FaqCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return faq_service.create(
            content=payload.to_content(),
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.put("/api/faqs/{faq_id}")
    async def edit_faq(
        faq_id: str,
        payload: FaqEditRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return faq_service.edit(
            faq_id=faq_id,
            content=payload.to_content(),
            actor=actor,
            expected_etag=payload.expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/tests")
    async def add_faq_test(
        faq_id: str,
        version_id: str,
        payload: FaqTestCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return faq_service.add_test(
            faq_id=faq_id,
            version_id=version_id,
            kind=payload.kind,
            utterance=payload.utterance,
            expected_audience_group_ids=payload.expected_audience_group_ids,
            source_type=payload.source_type,
            source_correlation_id=payload.source_correlation_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
