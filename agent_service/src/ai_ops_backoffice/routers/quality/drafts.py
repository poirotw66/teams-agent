"""Quality case document and FAQ draft creation routes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from ...faq_domain import FaqContent, FaqValidationError
from ...knowledge_bridge.capabilities import has_knowledge_capability
from ...request_models import QualityDocumentDraftRequest, QualityFaqDraftRequest
from .content_helpers import build_document_draft_body
from .context import QualityRouteContext


def register_document_draft_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    quality_service = ctx.quality_service
    knowledge_client = ctx.knowledge_client

    @app.post("/api/quality-cases/{case_id}/document-draft")
    async def create_quality_case_document_draft(
        case_id: str,
        payload: QualityDocumentDraftRequest,
        correlation_id_value: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        if not has_knowledge_capability(actor, "knowledge.create"):
            raise HTTPException(
                status_code=403,
                detail="建立知識文件草稿需要 knowledge.create 權限。請確認角色或聯絡知識管理者。",
            )
        if not knowledge_client.configured:
            raise HTTPException(
                status_code=503,
                detail="知識整合（Knowledge Bridge）尚未啟用，無法建立文件草稿。",
            )
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        correlation = (correlation_id_value or "").strip() or uuid.uuid4().hex
        doc_body = build_document_draft_body(
            case_id=case_id,
            case=case,
            payload=payload,
            actor=actor,
        )
        portal_res = await knowledge_client.request(
            method="POST",
            relative_path="documents",
            actor=actor,
            correlation_id=correlation,
            json_body=doc_body,
        )
        if portal_res.status_code not in (200, 201):
            error_data = (
                portal_res.json()
                if portal_res.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            raise HTTPException(
                status_code=portal_res.status_code,
                detail=error_data.get("detail")
                or error_data.get("error", {}).get("message")
                or "建立知識文件失敗",
            )
        created_data = portal_res.json()
        doc_id = (created_data.get("document") or {}).get("document_id")
        if not doc_id:
            raise HTTPException(status_code=502, detail="知識門戶未回傳有效 document_id")
        try:
            linked = quality_service.link_content(
                case_id,
                faq_id=None,
                document_id=doc_id,
                expected_etag=payload.expected_case_etag,
                actor=actor,
            )
            return {
                **created_data,
                "case": linked["case"],
                "partialSuccess": False,
                "message": "文件草稿建立並成功關聯至案件。",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                **created_data,
                "case": case,
                "partialSuccess": True,
                "linkError": str(exc),
                "message": (
                    "文件草稿建立成功，但自動關聯至案件失敗。"
                    "請於案件中手動關聯既有文件 ID，請勿重複建立文件。"
                ),
            }


def register_faq_draft_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    quality_service = ctx.quality_service
    faq_service = ctx.faq_service

    @app.post("/api/quality-cases/{case_id}/faq-draft")
    async def create_quality_case_faq_draft(
        case_id: str,
        payload: QualityFaqDraftRequest,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        require_capability(actor, "ops.faq.write")
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        if not case["issue_type_id"]:
            raise FaqValidationError("Quality Case requires an issue type before creating a FAQ")
        content = FaqContent(
            faq_key=payload.faq_key,
            question=payload.question,
            answer=payload.answer,
            category=payload.category,
            keywords=payload.keywords,
            owner_unit_id=case["owner_unit_id"],
            business_contact=payload.business_contact,
            issue_type_ids=(case["issue_type_id"],),
            audience_type=payload.audience_type,
            audience_group_ids=payload.audience_group_ids,
            related_document_ids=payload.related_document_ids,
            effective_at=payload.effective_at,
            review_due_at=payload.review_due_at,
        )
        faq_result = faq_service.create(
            content=content,
            actor=actor,
            correlation_id=correlation_id,
        )
        linked = quality_service.link_content(
            case_id,
            faq_id=faq_result["faq"]["faq_id"],
            document_id=None,
            expected_etag=payload.expected_case_etag,
            actor=actor,
        )
        return {**faq_result, "case": linked["case"]}
