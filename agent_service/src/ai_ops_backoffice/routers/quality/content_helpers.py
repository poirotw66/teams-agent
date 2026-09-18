"""Helpers for quality case content linking and document drafts."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ...faq_domain import FaqNotFoundError, FaqValidationError
from ...request_models import QualityDocumentDraftRequest
from ...services.source_repository import prefer_document_source_record


async def resolve_document_owner_unit(
    *,
    query_service: Any,
    knowledge_client: Any,
    actor: Any,
    document_id: str,
    case_owner_unit_id: str,
) -> str:
    """Resolve a document owner unit via Portal, inventory, or SourceRecord fallback."""
    doc_owner_unit: str | None = None
    if knowledge_client.configured:
        try:
            portal_res = await knowledge_client.request(
                method="GET",
                relative_path=f"documents/{document_id}",
                actor=actor,
                correlation_id=uuid.uuid4().hex,
            )
            if portal_res.status_code == 200:
                portal_data = portal_res.json().get("document") or {}
                doc_owner_unit = portal_data.get("owner_unit_id")
            elif portal_res.status_code == 403:
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
            query=document_id,
            limit=100,
        )
        document = next(
            (
                item
                for item in inventory.get("items", [])
                if item.get("documentId") == document_id
            ),
            None,
        )
        if document is not None:
            doc_owner_unit = document.get("ownerUnitId")
    if doc_owner_unit is None:
        # Shared source contract: Portal inventory may lag behind SourceRecord.
        tenant_id = getattr(actor, "tenant_id", None) or "default"
        records = await query_service.source_repository.list_source_records_for_document(
            tenant_id,
            document_id,
        )
        preferred = prefer_document_source_record(records)
        if preferred is None:
            raise FaqNotFoundError(document_id)
        doc_owner_unit = preferred.owner_unit_id or case_owner_unit_id
    return doc_owner_unit


def build_document_draft_body(
    *,
    case_id: str,
    case: dict[str, Any],
    payload: QualityDocumentDraftRequest,
    actor: Any,
) -> dict[str, Any]:
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    due_date = (datetime.now(timezone.utc) + timedelta(days=180)).strftime("%Y-%m-%d")
    doc_title = (payload.title or case.get("title") or "未命名改善文件").strip()[:256]
    doc_summary = (
        payload.summary or f"由品質案件 {case_id} 建立之知識改善文件草稿。"
    ).strip()[:2000]
    doc_category = (payload.category or case.get("issue_type_id") or "Operations").strip()[:128]
    contact = (payload.business_contact or actor.display_name or actor.user_id).strip()[:256]
    content = payload.markdown_content or (
        f"# {doc_title}\n\n"
        f"## 適用問題\n\n{case.get('description', '')}\n\n"
        "## 建議處理指引\n\n1. 步驟說明...\n"
    )
    return {
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
