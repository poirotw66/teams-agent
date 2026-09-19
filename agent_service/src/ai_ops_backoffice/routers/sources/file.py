"""Source original-file download route."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response

from knowledge_core.artifact_ports import sanitize_filename
from operations_core.document_authorization import (
    DocumentAccessDeniedError,
    ensure_document_access,
)

from .context import SourcesRouteContext
from .file_streaming import stream_artifact_file, stream_local_file


async def _handle_source_file(
    source_ref_id: str,
    request: Request,
    actor: Any,
    *,
    ctx: SourcesRouteContext,
) -> Response:
    query_service = ctx.query_service
    require_capability = ctx.require_capability
    audit_read = ctx.audit_read

    require_capability(actor, "ops.conversations.read")

    tenant_id = getattr(actor, "tenant_id", None) or "default"
    trace = query_service.source_trace
    if hasattr(trace, "resolve_source_ref_async"):
        source = await trace.resolve_source_ref_async(source_ref_id, tenant_id=tenant_id)
    else:
        source = trace.resolve_source_ref(source_ref_id, tenant_id=tenant_id)
    if source is None or not source.original_asset_available:
        raise HTTPException(
            status_code=404,
            detail="Original source file is not available or access denied.",
        )
    if source.mapping_status == "LEGACY_UNVERIFIED":
        raise HTTPException(
            status_code=404,
            detail="Original source file is not available or access denied.",
        )

    try:
        ensure_document_access(actor, source, action="download")
    except DocumentAccessDeniedError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    raw_name = source.original_asset_name or "source-file"
    safe_name = sanitize_filename(raw_name)
    range_header = request.headers.get("range")
    artifact_store = getattr(query_service.source_trace, "artifact_storage", None)

    artifact_response = await stream_artifact_file(
        request=request,
        actor=actor,
        source=source,
        tenant_id=tenant_id,
        safe_name=safe_name,
        range_header=range_header,
        artifact_store=artifact_store,
        audit_read=audit_read,
    )
    if artifact_response is not None:
        return artifact_response

    local_response = await stream_local_file(
        actor=actor,
        source=source,
        safe_name=safe_name,
        range_header=range_header,
        audit_read=audit_read,
    )
    if local_response is not None:
        return local_response

    raise HTTPException(
        status_code=404,
        detail="Original source file is not available or access denied.",
    )


def register_file_routes(app: FastAPI, ctx: SourcesRouteContext) -> None:
    current_actor = ctx.current_actor

    @app.get("/api/sources/{source_ref_id}/file", operation_id="source_file_get")
    async def source_file(
        source_ref_id: str,
        request: Request,
        actor: Any = Depends(current_actor),
    ) -> Response:
        """Download or stream an original source file with unified ACL and HTTP Range support."""
        return await _handle_source_file(source_ref_id, request, actor, ctx=ctx)

    @app.head("/api/sources/{source_ref_id}/file", operation_id="source_file_head")
    async def source_file_head(
        source_ref_id: str,
        request: Request,
        actor: Any = Depends(current_actor),
    ) -> Response:
        """Inspect headers for an original source file with unified ACL and HTTP Range support."""
        return await _handle_source_file(source_ref_id, request, actor, ctx=ctx)


