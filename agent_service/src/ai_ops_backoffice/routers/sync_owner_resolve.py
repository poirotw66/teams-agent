"""Sync job owner-unit resolution for create_sync_job."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..faq_domain.errors import FaqNotFoundError, FaqValidationError


async def resolve_sync_owner_unit_id(
    *,
    payload: Any,
    actor: Any,
    resolved_settings: Any,
    faq_service: Any,
    query_service: Any,
) -> str:
    owner_unit_id = resolved_settings.default_owner_unit_id
    if payload.scope_type == "FAQ":
        owners = set()
        for faq_id in payload.scope_ids:
            detail = faq_service.detail(faq_id=faq_id, actor=actor)
            owners.add(detail["versions"][-1]["content"]["owner_unit_id"])
        if len(owners) != 1:
            raise FaqValidationError("FAQ sync scope must belong to one owner unit")
        return next(iter(owners))
    if payload.scope_type == "DOCUMENT":
        inventory = await query_service.list_documents(actor, limit=100)
        if inventory.get("portalStatus") != "available":
            raise HTTPException(
                status_code=503, detail="Knowledge inventory is unavailable."
            )
        selected = [
            item
            for item in inventory["items"]
            if item.get("documentId") in payload.scope_ids
        ]
        if len(selected) != len(set(payload.scope_ids)):
            raise FaqNotFoundError("one or more sync documents were not found")
        owners = {item.get("ownerUnitId") for item in selected}
        if None in owners or len(owners) != 1:
            raise FaqValidationError(
                "document sync scope must belong to one owner unit"
            )
        return next(iter(owners))
    return owner_unit_id
