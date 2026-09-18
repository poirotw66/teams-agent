"""Source resolve-by-document route."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query

from .context import SourcesRouteContext
from .resolve_helpers import resolve_authorized_preview


def register_resolve_routes(app: FastAPI, ctx: SourcesRouteContext) -> None:
    query_service = ctx.query_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    audit_read = ctx.audit_read

    @app.get("/api/sources")
    async def resolve_sources(
        documentId: str | None = Query(default=None),
        versionId: str | None = Query(default=None),
        releaseId: str | None = Query(default=None),
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        """Resolve SourceRecords for a document without requiring Portal inventory."""

        require_capability(actor, "ops.conversations.read")
        document_id = (documentId or "").strip()
        if not document_id:
            raise HTTPException(
                status_code=400,
                detail="documentId query parameter is required.",
            )
        source, records, payload = await resolve_authorized_preview(
            query_service=query_service,
            actor=actor,
            document_id=document_id,
            version_id=(versionId or "").strip() or None,
            release_id=(releaseId or "").strip() or None,
        )
        await audit_read(
            actor,
            "query.source_resolve_by_document",
            source.source_ref_id,
            after={
                "documentId": source.document_id,
                "versionId": source.version_id,
                "releaseId": source.release_id,
                "mappingStatus": source.mapping_status,
                "matchCount": len(records),
            },
        )
        return payload
