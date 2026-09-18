"""Draft and version asset read routes for Knowledge Portal documents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse

from knowledge_portal.draft_assets import slug_from_title
from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService


def register_documents_asset_read_routes(
    app: FastAPI,
    *,
    service: PortalService,
    authorize: Callable[..., None],
    current_actor: Callable[..., PortalActor],
    handle_errors: Callable[[Exception], HTTPException],
    **_: Any,
) -> None:
    @app.get("/api/documents/{document_id}/draft/assets")
    async def list_draft_assets(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.list_draft_assets(actor, document_id)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/{document_id}/draft/assets/{filename}")
    async def get_draft_asset(
        document_id: str,
        filename: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        detail = await service.get_document(actor, document_id)
        if detail.draft_version is None:
            raise HTTPException(status_code=404, detail="Draft version not found.")
        slug = detail.draft_version.asset_slug or slug_from_title(detail.draft_version.title)
        try:
            path, media_type = service.read_draft_asset(
                document_id,
                detail.draft_version.version_id,
                slug,
                filename,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc
        return FileResponse(path, media_type=media_type)

    @app.get("/api/v1/documents/{document_id}/versions/{version_id}/assets/{filename}")
    async def get_document_version_asset(
        document_id: str,
        version_id: str,
        filename: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            payload, media_type = await service.read_version_asset(
                actor,
                document_id,
                version_id,
                filename,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Asset not found.") from exc
        except Exception as exc:
            raise handle_errors(exc) from exc
        return Response(
            content=payload,
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
            },
        )
