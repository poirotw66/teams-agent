"""Source citation preview route."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from operations_core.document_authorization import (
    DocumentAccessDeniedError,
    ensure_document_access,
)

from .context import SourcesRouteContext


def register_preview_routes(app: FastAPI, ctx: SourcesRouteContext) -> None:
    query_service = ctx.query_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    audit_read = ctx.audit_read

    @app.get("/api/sources/{source_ref_id}")
    async def source_preview(
        source_ref_id: str,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        """Return an authorized, release-pinned citation preview.

        The source reference is opaque. Raw object-store paths and signed
        URLs never cross this endpoint; an original file, when available, is
        exposed only through the sibling authenticated download route.
        """
        require_capability(actor, "ops.conversations.read")
        tenant_id = getattr(actor, "tenant_id", None) or "default"
        trace = query_service.source_trace
        if hasattr(trace, "resolve_source_ref_async"):
            source = await trace.resolve_source_ref_async(source_ref_id, tenant_id=tenant_id)
        else:
            source = trace.resolve_source_ref(source_ref_id, tenant_id=tenant_id)
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

        await audit_read(
            actor,
            "query.source_preview",
            source.source_ref_id,
            after={
                "documentId": source.document_id,
                "versionId": source.version_id,
                "releaseId": source.release_id,
                "mappingStatus": source.mapping_status,
            },
        )
        return payload
