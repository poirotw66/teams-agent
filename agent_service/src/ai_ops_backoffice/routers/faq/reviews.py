"""FAQ submit and review transition routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header

from ...request_models import FaqReviewRequest, FaqTransitionRequest
from .context import FaqRouteContext


def register_faq_review_routes(app: FastAPI, ctx: FaqRouteContext) -> None:
    faq_service = ctx.faq_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/submit")
    async def submit_faq(
        faq_id: str,
        version_id: str,
        payload: FaqTransitionRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return faq_service.submit(
            faq_id=faq_id,
            version_id=version_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/review")
    async def review_faq(
        faq_id: str,
        version_id: str,
        payload: FaqReviewRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.review")
        return faq_service.review(
            faq_id=faq_id,
            version_id=version_id,
            approve=payload.approve,
            reason=payload.reason,
            actor=actor,
            expected_etag=payload.expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
