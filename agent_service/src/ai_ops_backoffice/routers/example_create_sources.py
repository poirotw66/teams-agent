"""Helpers that resolve example create sources before persistence."""

from __future__ import annotations

from fastapi import HTTPException

from ..faq_domain import FaqNotFoundError, FaqValidationError


def resolve_faq_example_source(faq: dict[str, object], version_id: str) -> dict[str, object]:
    source_version = next(
        (item for item in faq["versions"] if item["version_id"] == version_id),
        None,
    )
    if source_version is None:
        raise FaqNotFoundError(version_id)
    return source_version


async def resolve_document_example_source(
    query_service,
    actor,
    document_id: str,
    version_id: str,
) -> str:
    inventory = await query_service.list_documents(actor, query=document_id, limit=100)
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
    return str(owner_unit_id)


async def resolve_conversation_example_source(
    query_service,
    actor,
    conversation_id: str,
) -> tuple[str, str | None]:
    source_conversation = await query_service.conversation_detail(actor, conversation_id)
    if source_conversation is None:
        raise FaqNotFoundError(conversation_id)
    owner_unit_id = source_conversation.get("ownerUnitId")
    if not owner_unit_id:
        raise FaqValidationError("conversation owner unit is unavailable or ambiguous")
    turns = source_conversation.get("turns") or []
    source_correlation_id = turns[-1].get("correlationId") if turns else None
    return str(owner_unit_id), source_correlation_id
