from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from ..faq_domain import FaqContent
from ..knowledge_bridge.capabilities import has_knowledge_capability
from ..request_models import (
    QualityCandidateMergeRequest,
    QualityCandidateRefreshRequest,
    QualityCaseTransitionRequest,
    QualityCaseUpdateRequest,
    QualityContentLinkRequest,
    QualityDocumentDraftRequest,
    QualityFaqDraftRequest,
    QuestionClusterCorrectionRequest,
)


def register_quality_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    quality_service,
    faq_service,
    knowledge_client,
    quality_metrics_by_issue,
    enrich_quality_issue_display,
    current_actor,
    require_capability,
) -> None:
    _enrich_quality_issue_display = enrich_quality_issue_display

    @app.get("/api/quality-cases")
    async def list_quality_cases(
        status: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = [
            _enrich_quality_issue_display(item)
            for item in quality_service.list_cases(actor=actor, status=status)
        ]
        return {"items": items, "total": len(items)}

    @app.get("/api/quality-cases/{case_id}")
    async def get_quality_case(case_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        detail = quality_service.case_detail(case_id, actor=actor)
        return {
            **detail,
            "case": _enrich_quality_issue_display(detail["case"]),
        }

    @app.put("/api/quality-cases/{case_id}")
    async def update_quality_case(
        case_id: str,
        payload: QualityCaseUpdateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.update_case(
            case_id,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            assignee_id=payload.assignee_id,
            target_due_at=payload.target_due_at,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.post("/api/quality-cases/{case_id}/transition")
    async def transition_quality_case(
        case_id: str,
        payload: QualityCaseTransitionRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        capability = (
            "ops.quality.resolve"
            if payload.status in {"RESOLVED", "WONT_FIX", "DUPLICATE"}
            else "ops.quality.write"
        )
        require_capability(actor, capability)
        return quality_service.transition_case(
            case_id,
            status=payload.status,
            reason=payload.reason,
            resolution_type=payload.resolution_type,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.post("/api/quality-cases/{case_id}/content")
    async def link_quality_case_content(
        case_id: str,
        payload: QualityContentLinkRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        if payload.faq_id:
            faq = faq_service.detail(faq_id=payload.faq_id, actor=actor)
            if faq["versions"][-1]["content"]["owner_unit_id"] != case["owner_unit_id"]:
                raise FaqValidationError("linked FAQ must belong to the Quality Case owner unit")
        if payload.document_id:
            doc_owner_unit: str | None = None
            if knowledge_client.configured:
                try:
                    p_res = await knowledge_client.request(
                        method="GET",
                        relative_path=f"documents/{payload.document_id}",
                        actor=actor,
                        correlation_id=uuid.uuid4().hex,
                    )
                    if p_res.status_code == 200:
                        p_data = p_res.json().get("document") or {}
                        doc_owner_unit = p_data.get("owner_unit_id")
                    elif p_res.status_code == 403:
                        raise FaqValidationError(
                            "linked document must belong to the Quality Case owner unit"
                        )
                except FaqValidationError:
                    raise
                except Exception:  # noqa: BLE001
                    doc_owner_unit = None
            if doc_owner_unit is None:
                inventory = await query_service.list_documents(
                    actor,
                    query=payload.document_id,
                    limit=100,
                )
                document = next(
                    (
                        item for item in inventory.get("items", [])
                        if item.get("documentId") == payload.document_id
                    ),
                    None,
                )
                if document is None:
                    raise FaqNotFoundError(payload.document_id)
                doc_owner_unit = document.get("ownerUnitId")
            if doc_owner_unit != case["owner_unit_id"]:
                raise FaqValidationError("linked document must belong to the Quality Case owner unit")
        return quality_service.link_content(
            case_id,
            faq_id=payload.faq_id,
            document_id=payload.document_id,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.post("/api/quality-cases/{case_id}/document-draft")
    async def create_quality_case_document_draft(
        case_id: str,
        payload: QualityDocumentDraftRequest,
        correlation_id_value: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
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

        now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        due_date = (datetime.now(timezone.utc) + timedelta(days=180)).strftime("%Y-%m-%d")
        doc_title = (payload.title or case.get("title") or "未命名改善文件").strip()[:256]
        doc_summary = (
            payload.summary or f"由品質案件 {case_id} 建立之知識改善文件草稿。"
        ).strip()[:2000]
        doc_category = (
            payload.category or case.get("issue_type_id") or "Operations"
        ).strip()[:128]
        contact = (payload.business_contact or actor.display_name or actor.user_id).strip()[:256]
        content = payload.markdown_content or (
            f"# {doc_title}\n\n"
            f"## 適用問題\n\n{case.get('description', '')}\n\n"
            "## 建議處理指引\n\n1. 步驟說明...\n"
        )
        doc_body = {
            "title": doc_title,
            "summary": doc_summary,
            "category": doc_category,
            "owner_unit_id": case["owner_unit_id"],
            "business_contact": contact,
            "audience_type": "ALL_EMPLOYEES",
            "audience_group_ids": [],
            "effective_at": now_date,
            "review_due_at": due_date,
            "change_summary": f"由品質案件 {case_id} 建立草稿",
            "change_reason": f"品質案件 {case_id} 知識改善：{case.get('description', '')[:200]}",
            "markdown_content": content,
            "source_type": "MARKDOWN_PASTE",
        }

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
                "message": "文件草稿建立成功，但自動關聯至案件失敗。請於案件中手動關聯既有文件 ID，請勿重複建立文件。",
            }

    @app.post("/api/quality-cases/{case_id}/faq-draft")
    async def create_quality_case_faq_draft(
        case_id: str,
        payload: QualityFaqDraftRequest,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
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

    @app.post("/api/quality-cases/{case_id}/observation/refresh")
    async def refresh_quality_case_observation(
        case_id: str,
        payload: FaqTransitionRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        metrics = (await quality_metrics_by_issue(actor)).get(case["issue_type_id"] or "", {})
        return quality_service.record_observation(
            case_id,
            metrics=metrics,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.get("/api/quality-candidates")
    async def list_quality_candidates(
        status: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = [
            _enrich_quality_issue_display(item)
            for item in quality_service.list_candidates(actor=actor, status=status)
        ]
        return {"items": items, "total": len(items)}

    @app.post("/api/quality-candidates/refresh")
    async def refresh_quality_candidates(
        payload: QualityCandidateRefreshRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        seeds = await query_service.quality_candidate_seeds(actor, days=payload.days)
        for seed in seeds:
            quality_service.add_candidate(**seed, actor=actor)
        items = quality_service.list_candidates(actor=actor, status="OPEN")
        return {"items": items, "total": len(items), "scanned": len(seeds)}

    @app.post("/api/quality-candidates/merge")
    async def merge_quality_candidates(
        payload: QualityCandidateMergeRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.merge_candidates(
            payload.candidate_ids,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            assignee_id=payload.assignee_id,
            target_due_at=payload.target_due_at,
            actor=actor,
        )

    @app.get("/api/gaps/summary")
    async def gap_summary(
        days: int = Query(default=30, ge=1, le=365),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        issues = await query_service.issues_summary(actor, days=days)
        weights = {
            "frequency": 30.0,
            "noAnswerRate": 20.0,
            "negativeFeedbackRate": 25.0,
            "handoffRate": 15.0,
            "estimatedCostUsd": 10.0,
        }
        items = []
        max_frequency = max((item["count"] for item in issues["items"]), default=1)
        max_cost = max((item["estimatedCostUsd"] for item in issues["items"]), default=1) or 1
        for issue in issues["items"]:
            components = {
                "frequency": round(issue["count"] / max_frequency * weights["frequency"], 4),
                "noAnswerRate": round(issue["noAnswerRate"] * weights["noAnswerRate"], 4),
                "negativeFeedbackRate": round(
                    issue["negativeFeedbackRate"] * weights["negativeFeedbackRate"], 4
                ),
                "handoffRate": round(issue["handoffRate"] * weights["handoffRate"], 4),
                "estimatedCostUsd": round(
                    issue["estimatedCostUsd"] / max_cost * weights["estimatedCostUsd"], 4
                ),
            }
            items.append({**issue, "gapScore": round(sum(components.values()), 4), "components": components})
        items.sort(key=lambda item: item["gapScore"], reverse=True)
        return {
            "scoreVersion": "gap-score-v1",
            "weights": weights,
            "taxonomyVersion": issues["taxonomyVersion"],
            "items": items,
        }

    @app.get("/api/question-clusters")
    async def list_question_clusters(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = quality_service.list_clusters(actor=actor)
        return {"items": items, "total": len(items)}

    @app.post("/api/question-clusters/generate")
    async def generate_question_clusters(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.generate_clusters(actor=actor)

    @app.post("/api/question-clusters/correct")
    async def correct_question_clusters(
        payload: QuestionClusterCorrectionRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.correct_clusters(
            payload.cluster_ids,
            action=payload.action,
            name=payload.name,
            candidate_groups=payload.candidate_groups,
            actor=actor,
        )

