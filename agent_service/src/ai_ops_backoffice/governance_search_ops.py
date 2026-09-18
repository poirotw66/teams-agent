"""Collect cross-domain documents for governance unified search."""

from __future__ import annotations

from typing import Any

__all__ = ["collect_search_extras"]


def _faq_documents(faq_service: Any, actor: Any) -> list[dict[str, object]]:
    extras: list[dict[str, object]] = []
    for item in faq_service.list_faqs(actor=actor):
        faq = item.get("faq") or {}
        version = item.get("version") or {}
        content = version.get("content") or {}
        faq_status = str(version.get("status") or faq.get("status") or "PUBLISHED")
        extras.append(
            {
                "type": "FAQ",
                "id": str(faq.get("faq_id") or ""),
                "title": str(content.get("faq_key") or faq.get("faq_id") or ""),
                "snippet": str(content.get("question") or version.get("status") or "")[:160],
                "owner_unit_id": str(faq.get("owner_unit_id") or ""),
                "status": faq_status,
                "requiredCapability": "ops.faq.read",
            }
        )
    return extras


def _example_documents(example_service: Any, actor: Any) -> list[dict[str, object]]:
    extras: list[dict[str, object]] = []
    for item in example_service.list_examples(actor=actor)[:200]:
        example_status = str(item.get("status") or "VERIFIED")
        extras.append(
            {
                "type": "EXAMPLE",
                "id": str(item.get("example_id") or ""),
                "title": str(item.get("expected_issue_type_id") or item.get("label") or ""),
                "snippet": str(item.get("text") or "")[:160],
                "owner_unit_id": str(item.get("owner_unit_id") or ""),
                "status": example_status,
                "requiredCapability": "ops.examples.read",
            }
        )
    return extras


def _issue_type_documents(query_service: Any) -> list[dict[str, object]]:
    extras: list[dict[str, object]] = []
    taxonomy = getattr(query_service, "taxonomy", None)
    if taxonomy is None:
        return extras
    for issue in taxonomy.list_active():
        issue_id = getattr(issue, "issue_type_id", None) or getattr(issue, "id", "")
        display = getattr(issue, "display_name", None) or getattr(issue, "name", issue_id)
        desc = getattr(issue, "description", "") or getattr(issue, "category", "") or ""
        extras.append(
            {
                "type": "ISSUE_TYPE",
                "id": str(issue_id),
                "title": str(display),
                "snippet": f"{issue_id} {desc}"[:160],
                "owner_unit_id": str(getattr(issue, "owner_unit_id", "") or ""),
                "status": "ACTIVE",
                "requiredCapability": "ops.issues.read",
            }
        )
    return extras


async def _knowledge_documents(query_service: Any) -> list[dict[str, object]]:
    extras: list[dict[str, object]] = []
    doc_inv = await query_service._fetch_document_inventory()
    for doc in doc_inv.get("items", []):
        doc_id = str(doc.get("document_id") or "")
        title = str(doc.get("title") or doc.get("filename") or doc_id)
        desc = str(
            doc.get("description") or doc.get("category") or doc.get("owner_unit_id") or ""
        )
        doc_status = str(doc.get("status") or "PUBLISHED")
        extras.append(
            {
                "type": "KNOWLEDGE",
                "id": doc_id,
                "title": title,
                "snippet": f"{doc_id} {desc}"[:160],
                "owner_unit_id": str(doc.get("owner_unit_id") or ""),
                "status": doc_status,
                "requiredCapability": "ops.knowledge.read",
            }
        )
    return extras


async def _conversation_documents(
    query_service: Any, actor: Any, query: str
) -> list[dict[str, object]]:
    extras: list[dict[str, object]] = []
    conv_result = await query_service.list_conversations(actor, days=365, query=query, limit=20)
    for item in conv_result.get("items", []):
        turn_texts = []
        for turn in item.get("turns", []):
            if turn.get("userMessage"):
                turn_texts.append(str(turn["userMessage"]))
            if turn.get("aiReply"):
                turn_texts.append(str(turn["aiReply"]))
        matched_snippet = (
            " ".join(turn_texts) if turn_texts else f"{item.get('actorRef') or ''} {query}"
        )
        conv_status = str(item.get("status") or "CLOSED")
        extras.append(
            {
                "type": "CONVERSATION",
                "id": item["conversationId"],
                "title": f"對話 {item['conversationId']}",
                "snippet": matched_snippet[:160],
                "owner_unit_id": str(item.get("ownerUnitId") or ""),
                "status": conv_status,
                "requiredCapability": "ops.conversations.read",
            }
        )
    return extras


def _quality_case_documents(quality_service: Any, actor: Any) -> list[dict[str, object]]:
    extras: list[dict[str, object]] = []
    for case in quality_service.list_cases(actor=actor)[:200]:
        case_status = str(case.get("status") or "OPEN")
        extras.append(
            {
                "type": "QUALITY_CASE",
                "id": str(case.get("case_id") or ""),
                "title": str(case.get("title") or case.get("status") or ""),
                "snippet": str(case.get("description") or case.get("issue_type_id") or "")[:160],
                "owner_unit_id": str(case.get("owner_unit_id") or ""),
                "status": case_status,
                "requiredCapability": "ops.quality.read",
            }
        )
    return extras


async def collect_search_extras(
    *,
    actor: Any,
    query: str,
    faq_service: Any = None,
    example_service: Any = None,
    query_service: Any = None,
    quality_service: Any = None,
) -> tuple[list[dict[str, object]], list[str]]:
    extras: list[dict[str, object]] = []
    warnings: list[str] = []

    if faq_service is not None and actor.has_capability("ops.faq.read"):
        try:
            extras.extend(_faq_documents(faq_service, actor))
        except Exception as exc:
            warnings.append(f"FAQ 資料來源讀取失敗：{exc}")

    if example_service is not None and actor.has_capability("ops.examples.read"):
        try:
            extras.extend(_example_documents(example_service, actor))
        except Exception as exc:
            warnings.append(f"Few-Shot 範例資料來源讀取失敗：{exc}")

    if query_service is not None and actor.has_capability("ops.issues.read"):
        try:
            extras.extend(_issue_type_documents(query_service))
        except Exception as exc:
            warnings.append(f"問題分類資料來源讀取失敗：{exc}")

    if query_service is not None and actor.has_capability("ops.knowledge.read"):
        try:
            extras.extend(await _knowledge_documents(query_service))
        except Exception as exc:
            warnings.append(f"知識文件資料來源讀取失敗：{exc}")

    if query_service is not None and actor.has_capability("ops.conversations.read") and query:
        try:
            extras.extend(await _conversation_documents(query_service, actor, query))
        except Exception as exc:
            warnings.append(f"對話歷史資料來源讀取失敗：{exc}")

    if quality_service is not None and actor.has_capability("ops.quality.read"):
        try:
            extras.extend(_quality_case_documents(quality_service, actor))
        except Exception as exc:
            warnings.append(f"品質案件資料來源讀取失敗：{exc}")

    return extras, warnings
