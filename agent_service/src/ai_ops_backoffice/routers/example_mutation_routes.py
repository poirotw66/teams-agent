"""Example update / review / retire routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header

from ..request_models import ExampleRetireRequest, ExampleReviewRequest, ExampleUpdateRequest


def register_example_mutation_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    example_service,
    faq_service,
    current_actor,
    require_capability,
) -> None:
    del resolved_settings, query_service, faq_service

    @app.put("/api/examples/{example_id}")
    async def update_example(
        example_id: str,
        payload: ExampleUpdateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        return example_service.update(
            example_id,
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
            expected_etag=payload.expected_etag,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/examples/{example_id}/review")
    async def review_example(
        example_id: str,
        payload: ExampleReviewRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.verify")
        return example_service.review(
            example_id,
            approve=payload.approve,
            reason=payload.reason,
            expected_etag=payload.expected_etag,
            dataset_version=payload.dataset_version,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/examples/{example_id}/retire")
    async def retire_example(
        example_id: str,
        payload: ExampleRetireRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.retire")
        return example_service.retire(
            example_id,
            reason=payload.reason,
            expected_etag=payload.expected_etag,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
