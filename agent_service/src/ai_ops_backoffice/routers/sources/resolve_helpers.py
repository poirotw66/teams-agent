"""Shared helpers for resolving authorized source preview payloads."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from operations_core.document_authorization import (
    DocumentAccessDeniedError,
    ensure_document_access,
)

from ...services.source_repository import prefer_document_source_record


def active_release_id_or_none(query_service: Any) -> str | None:
    if not hasattr(query_service, "source_trace"):
        return None
    trace = query_service.source_trace
    if not hasattr(trace, "active_release_id"):
        return None
    try:
        return trace.active_release_id()
    except Exception:
        return None


async def resolve_authorized_preview(
    *,
    query_service: Any,
    actor: Any,
    document_id: str,
    version_id: str | None,
    release_id: str | None,
) -> tuple[Any, list[Any], dict[str, Any]]:
    """Return (source, matching records, preview payload) or raise HTTPException."""
    tenant_id = getattr(actor, "tenant_id", None) or "default"
    records = await query_service.source_trace.source_repository.list_source_records_for_document(
        tenant_id,
        document_id,
    )
    target_release_id = release_id or active_release_id_or_none(query_service)
    preferred = prefer_document_source_record(
        records,
        version_id=version_id,
        release_id=target_release_id,
    )
    if preferred is None:
        raise HTTPException(
            status_code=404,
            detail="Source reference not found or access denied.",
        )
    source = query_service.source_trace.resolve_source_ref(
        preferred.source_ref_id, tenant_id=tenant_id
    )
    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source reference not found or access denied.",
        )
    try:
        ensure_document_access(actor, source, action="preview")
    except DocumentAccessDeniedError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    payload = query_service.source_trace.preview_payload(source)
    payload["previewUrl"] = f"/api/sources/{source.source_ref_id}"
    if source.original_asset_available and source.mapping_status != "LEGACY_UNVERIFIED":
        payload["downloadUrl"] = f"/api/sources/{source.source_ref_id}/file"
    return source, records, payload
