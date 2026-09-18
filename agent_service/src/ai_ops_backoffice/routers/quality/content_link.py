"""Quality case content linking routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from ...faq_domain import FaqValidationError
from ...request_models import QualityContentLinkRequest
from .content_helpers import resolve_document_owner_unit
from .context import QualityRouteContext


def register_content_link_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    quality_service = ctx.quality_service
    faq_service = ctx.faq_service
    knowledge_client = ctx.knowledge_client
    query_service = ctx.query_service

    @app.post("/api/quality-cases/{case_id}/content")
    async def link_quality_case_content(
        case_id: str,
        payload: QualityContentLinkRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        if payload.faq_id:
            faq = faq_service.detail(faq_id=payload.faq_id, actor=actor)
            if faq["versions"][-1]["content"]["owner_unit_id"] != case["owner_unit_id"]:
                raise FaqValidationError("linked FAQ must belong to the Quality Case owner unit")
        if payload.document_id:
            doc_owner_unit = await resolve_document_owner_unit(
                query_service=query_service,
                knowledge_client=knowledge_client,
                actor=actor,
                document_id=payload.document_id,
                case_owner_unit_id=case["owner_unit_id"],
            )
            if doc_owner_unit != case["owner_unit_id"]:
                raise FaqValidationError(
                    "linked document must belong to the Quality Case owner unit"
                )
        return quality_service.link_content(
            case_id,
            faq_id=payload.faq_id,
            document_id=payload.document_id,
            expected_etag=payload.expected_etag,
            actor=actor,
        )
