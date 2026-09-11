from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from agent_service.artifact_storage import sanitize_filename
from agent_service.document_authorization import (
    DocumentAccessDeniedError,
    ensure_document_access,
)


def parse_range_header(range_header: str | None, total_size: int) -> tuple[int, int] | None:
    """Parse an HTTP Range header string into a 0-indexed [start, end] byte tuple."""
    if not range_header or not range_header.startswith("bytes="):
        return None
    try:
        spec = range_header[6:].strip()
        parts = spec.split("-", 1)
        if len(parts) != 2:
            return None
        start_str, end_str = parts[0].strip(), parts[1].strip()
        if start_str and end_str:
            start = int(start_str)
            end = int(end_str)
        elif start_str:
            start = int(start_str)
            end = total_size - 1
        elif end_str:
            suffix_len = int(end_str)
            start = max(0, total_size - suffix_len)
            end = total_size - 1
        else:
            return None
        if start > end or start >= total_size or start < 0:
            return None
        end = min(end, total_size - 1)
        return (start, end)
    except (ValueError, TypeError):
        return None


def register_sources_routes(
    app: FastAPI,
    *,
    query_service: Any,
    current_actor: Callable[..., Any],
    require_capability: Callable[[Any, str], None],
    audit_read: Callable[..., Any],
) -> None:
    """Register HTTP read routes for source citation preview and file streaming."""

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
        source = query_service._source_trace.resolve_source_ref(
            source_ref_id, tenant_id=tenant_id
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

        payload = query_service._source_trace.preview_payload(source)
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

    @app.get("/api/sources/{source_ref_id}/file")
    async def source_file(
        source_ref_id: str,
        request: Request,
        actor: Any = Depends(current_actor),
    ) -> Response:
        """Download or stream an original source file with unified ACL and HTTP Range support."""
        require_capability(actor, "ops.conversations.read")
        tenant_id = getattr(actor, "tenant_id", None) or "default"
        source = query_service._source_trace.resolve_source_ref(
            source_ref_id, tenant_id=tenant_id
        )
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
        artifact_store = getattr(query_service._source_trace, "artifact_storage", None)

        # 1. Multi-instance / GCP Artifact Storage streaming
        if artifact_store is not None and source.artifact_ref:
            if range_header:
                rec = await artifact_store.get_artifact_record(tenant_id, source.artifact_ref)
                if rec is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Source artifact not found or access denied.",
                    )
                parsed_range = parse_range_header(range_header, rec.size)
                if parsed_range:
                    start, end = parsed_range
                    _, data = await artifact_store.get_artifact_range(
                        tenant_id, source.artifact_ref, start, end
                    )
                    await audit_read(
                        actor,
                        "query.source_file_range",
                        source.source_ref_id,
                        after={"start": start, "end": end, "documentId": source.document_id},
                    )
                    return Response(
                        content=data,
                        status_code=206,
                        headers={
                            "Content-Range": f"bytes {start}-{end}/{rec.size}",
                            "Accept-Ranges": "bytes",
                            "Content-Length": str(len(data)),
                            "Content-Type": rec.mime_type,
                            "Content-Disposition": f'inline; filename="{safe_name}"',
                            "X-Content-Type-Options": "nosniff",
                        },
                    )

            rec, stream = await artifact_store.get_artifact(tenant_id, source.artifact_ref)
            await audit_read(
                actor,
                "query.source_file",
                source.source_ref_id,
                after={"documentId": source.document_id, "versionId": source.version_id},
            )
            return StreamingResponse(
                stream,
                status_code=200,
                headers={
                    "Content-Length": str(rec.size),
                    "Accept-Ranges": "bytes",
                    "Content-Type": rec.mime_type,
                    "Content-Disposition": f'inline; filename="{safe_name}"',
                    "X-Content-Type-Options": "nosniff",
                },
            )

        # 2. Local filesystem file streaming fallback
        if source.original_asset_path and source.original_asset_path.is_file():
            file_size = source.original_asset_path.stat().st_size
            if range_header:
                parsed_range = parse_range_header(range_header, file_size)
                if parsed_range:
                    start, end = parsed_range
                    with source.original_asset_path.open("rb") as f:
                        f.seek(start)
                        data = f.read(end - start + 1)
                    await audit_read(
                        actor,
                        "query.source_file_range",
                        source.source_ref_id,
                        after={"start": start, "end": end, "documentId": source.document_id},
                    )
                    return Response(
                        content=data,
                        status_code=206,
                        headers={
                            "Content-Range": f"bytes {start}-{end}/{file_size}",
                            "Accept-Ranges": "bytes",
                            "Content-Length": str(len(data)),
                            "Content-Type": (
                                "application/pdf"
                                if safe_name.lower().endswith(".pdf")
                                else "application/octet-stream"
                            ),
                            "Content-Disposition": f'inline; filename="{safe_name}"',
                            "X-Content-Type-Options": "nosniff",
                        },
                    )
            await audit_read(
                actor,
                "query.source_file",
                source.source_ref_id,
                after={"documentId": source.document_id, "versionId": source.version_id},
            )
            return FileResponse(
                source.original_asset_path,
                filename=safe_name,
                headers={"Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff"},
            )

        raise HTTPException(
            status_code=404,
            detail="Original source file is not available or access denied.",
        )
