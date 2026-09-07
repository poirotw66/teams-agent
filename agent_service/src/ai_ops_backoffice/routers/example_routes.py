from __future__ import annotations

from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException

from ..faq_domain import FaqNotFoundError
from ..request_models import (
    ExampleCreateRequest,
    ExampleRetireRequest,
    ExampleReviewRequest,
    ExampleUpdateRequest,
)


def register_example_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    example_service,
    faq_service,
    current_actor,
    require_capability,
) -> None:
    @app.get("/api/examples")
    async def list_examples(
        source_type: Literal["FAQ", "DOCUMENT", "CONVERSATION", "MANUAL"] | None = None,
        source_id: str | None = None,
        status: Literal["DRAFT", "VERIFIED", "REJECTED", "RETIRED"] | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.read")
        items = example_service.list_examples(
            actor=actor,
            source_type=source_type,
            source_id=source_id,
            status=status,
        )
        return {"items": items, "total": len(items)}

    @app.get("/api/examples/{example_id}")
    async def get_example(example_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.examples.read")
        return example_service.detail(example_id, actor=actor)

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
        source_version = next(
            (item for item in faq["versions"] if item["version_id"] == version_id),
            None,
        )
        if source_version is None:
            raise FaqNotFoundError(version_id)
        return example_service.create(
            source_type="FAQ",
            source_id=faq_id,
            source_version_id=version_id,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=source_version["content"]["owner_unit_id"],
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
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
        return example_service.create(
            source_type="MANUAL",
            source_id=f"manual:{actor.user_id}",
            source_version_id=None,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=resolved_settings.default_owner_unit_id,
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

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
        inventory = await query_service.list_documents(
            actor,
            query=document_id,
            limit=100,
        )
        if inventory.get("portalStatus") != "available":
            raise HTTPException(status_code=503, detail="Knowledge inventory is unavailable.")
        source_document = next(
            (item for item in inventory["items"] if item.get("documentId") == document_id),
            None,
        )
        if source_document is None:
            raise FaqNotFoundError(document_id)
        valid_versions = {
            source_document.get("currentPublishedVersionId"),
            source_document.get("draftVersionId"),
        }
        if version_id not in valid_versions:
            raise FaqNotFoundError(version_id)
        owner_unit_id = source_document.get("ownerUnitId")
        if not owner_unit_id:
            raise FaqValidationError("document owner unit is unavailable")
        return example_service.create(
            source_type="DOCUMENT",
            source_id=document_id,
            source_version_id=version_id,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=owner_unit_id,
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
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
        source_conversation = await query_service.conversation_detail(actor, conversation_id)
        if source_conversation is None:
            raise FaqNotFoundError(conversation_id)
        owner_unit_id = source_conversation.get("ownerUnitId")
        if not owner_unit_id:
            raise FaqValidationError("conversation owner unit is unavailable or ambiguous")
        turns = source_conversation.get("turns") or []
        source_correlation_id = turns[-1].get("correlationId") if turns else None
        return example_service.create(
            source_type="CONVERSATION",
            source_id=conversation_id,
            source_version_id=None,
            source_correlation_id=source_correlation_id,
            owner_unit_id=owner_unit_id,
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

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

