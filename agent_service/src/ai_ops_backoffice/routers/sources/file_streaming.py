"""Source original-file download and Range streaming helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from ai_ops_backoffice.adapters.local_source_files import (
    is_readable_file,
    read_file_byte_range,
    read_file_size,
)

from .range_parsing import parse_range_header

AuditRead = Callable[..., Awaitable[Any]]


def _range_not_satisfiable(total_size: int) -> Response:
    return Response(
        status_code=416,
        headers={
            "Content-Range": f"bytes */{total_size}",
            "Accept-Ranges": "bytes",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def stream_artifact_file(
    *,
    request: Request,
    actor: Any,
    source: Any,
    tenant_id: str,
    safe_name: str,
    range_header: str | None,
    artifact_store: Any,
    audit_read: AuditRead,
) -> Response | None:
    """Stream from artifact storage when available; return None to try local fallback."""
    if artifact_store is None or not source.artifact_ref:
        return None

    if range_header:
        rec = await artifact_store.get_artifact_record(tenant_id, source.artifact_ref)
        if rec is None:
            raise HTTPException(
                status_code=404,
                detail="Source artifact not found or access denied.",
            )
        parsed_range = parse_range_header(range_header, rec.size)
        if parsed_range is None:
            return _range_not_satisfiable(rec.size)
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
    headers = {
        "Content-Length": str(rec.size),
        "Accept-Ranges": "bytes",
        "Content-Type": rec.mime_type,
        "Content-Disposition": f'inline; filename="{safe_name}"',
        "X-Content-Type-Options": "nosniff",
    }
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    return StreamingResponse(stream, status_code=200, headers=headers)


async def stream_local_file(
    *,
    actor: Any,
    source: Any,
    safe_name: str,
    range_header: str | None,
    audit_read: AuditRead,
) -> Response | None:
    """Stream from a local filesystem path when present; return None if unavailable."""
    path = source.original_asset_path
    if not is_readable_file(path):
        return None

    file_size = read_file_size(path)
    if range_header:
        parsed_range = parse_range_header(range_header, file_size)
        if parsed_range is None:
            return _range_not_satisfiable(file_size)
        start, end = parsed_range
        data = read_file_byte_range(path, start=start, end=end)
        await audit_read(
            actor,
            "query.source_file_range",
            source.source_ref_id,
            after={"start": start, "end": end, "documentId": source.document_id},
        )
        content_type = (
            "application/pdf"
            if safe_name.lower().endswith(".pdf")
            else "application/octet-stream"
        )
        return Response(
            content=data,
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(data)),
                "Content-Type": content_type,
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
        path,
        filename=safe_name,
        headers={"Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff"},
    )
