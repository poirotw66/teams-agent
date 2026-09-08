from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from ..request_models import (
    FaqCreateRequest,
    FaqEditRequest,
    FaqReasonRequest,
    FaqReviewRequest,
    FaqTestCreateRequest,
    FaqTransitionRequest,
)


def register_faq_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    faq_service,
    quality_service,
    quality_metrics_by_issue,
    current_actor,
    require_capability,
    audit_read,
) -> None:
    @app.get("/api/faqs")
    async def list_faqs(
        status: str | None = None,
        owner_unit_id: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
        query: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        items = faq_service.list_faqs(actor=actor)
        if status:
            items = [item for item in items if item["faq"]["status"] == status]
        if owner_unit_id:
            items = [
                item for item in items
                if item["version"]["content"]["owner_unit_id"] == owner_unit_id
            ]
        if category:
            cat_needle = category.casefold()
            items = [
                item for item in items
                if str(item["version"]["content"].get("category") or "").casefold() == cat_needle
            ]
        if keyword:
            keyword_needle = keyword.casefold()
            items = [
                item for item in items
                if any(
                    keyword_needle in str(value).casefold()
                    for value in (item["version"]["content"].get("keywords") or ())
                )
            ]
        if query:
            needle = query.casefold()
            items = [
                item for item in items
                if any(
                    needle in str(value).casefold()
                    for value in (
                        item["faq"]["faq_key"],
                        item["version"]["content"]["question"],
                        item["version"]["content"].get("answer") or "",
                        item["version"]["content"].get("category") or "",
                        " ".join(item["version"]["content"].get("keywords") or ()),
                    )
                )
            ]
        return {"items": items, "total": len(items)}

    @app.get("/api/faqs/{faq_id}")
    async def get_faq(faq_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        return faq_service.detail(faq_id=faq_id, actor=actor)

    @app.get("/api/faqs/{faq_id}/performance")
    async def get_faq_performance(
        faq_id: str,
        days: int | None = None,
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        detail = faq_service.detail(faq_id=faq_id, actor=actor)
        faq_key = detail["faq"]["faq_key"]
        return await query_service.faq_performance(
            actor,
            faq_key=faq_key,
            faq_id=faq_id,
            days=days,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
        )

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
