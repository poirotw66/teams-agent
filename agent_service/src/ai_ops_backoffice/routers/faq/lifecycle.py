"""FAQ activate, rollback, and disable lifecycle routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header

from ...request_models import FaqReasonRequest
from .context import FaqRouteContext


def register_faq_lifecycle_routes(app: FastAPI, ctx: FaqRouteContext) -> None:
    faq_service = ctx.faq_service
    quality_service = ctx.quality_service
    quality_metrics_by_issue = ctx.quality_metrics_by_issue
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/activate")
    async def activate_faq(
        faq_id: str,
        version_id: str,
        payload: FaqReasonRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.activate")
        result = faq_service.activate(
            faq_id=faq_id,
            version_id=version_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        observing = quality_service.observe_faq(
            faq_id,
            baseline_by_issue=await quality_metrics_by_issue(actor),
            actor=actor,
        )
        return {**result, "observingCases": observing["items"]}

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/rollback")
    async def rollback_faq(
        faq_id: str,
        version_id: str,
        payload: FaqReasonRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.activate")
        result = faq_service.rollback(
            faq_id=faq_id,
            version_id=version_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        observing = quality_service.observe_faq(
            faq_id,
            baseline_by_issue=await quality_metrics_by_issue(actor),
            actor=actor,
        )
        return {**result, "observingCases": observing["items"]}

    @app.post("/api/faqs/{faq_id}/disable")
    async def disable_faq(
        faq_id: str,
        payload: FaqReasonRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.disable")
        return faq_service.disable(
            faq_id=faq_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
