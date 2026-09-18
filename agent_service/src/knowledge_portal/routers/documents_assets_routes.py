"""Knowledge Portal documents and ingestion HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse

from knowledge_portal.draft_assets import slug_from_title
from knowledge_portal.models import (
    PortalActor,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_assets_routes(
    app: FastAPI,
    *,
    settings: PortalSettings,
    service: PortalService,
    pdf_job_store: Any,
    authorize: Callable[..., None],
    current_actor: Callable[..., PortalActor],
    correlation_id: Callable[..., str],
    idempotency_key: Callable[..., str | None],
    handle_errors: Callable[[Exception], HTTPException],
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

    @app.post("/api/documents/{document_id}/draft/assets")
    async def upload_draft_assets(
        document_id: str,
        files: list[UploadFile] = File(...),
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        uploads: list[tuple[str, bytes]] = []
        for upload in files:
            uploads.append((upload.filename or "image.png", await upload.read()))
        try:
            return await service.upload_draft_assets(
                actor,
                document_id,
                uploads,
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.delete("/api/documents/{document_id}/draft/assets/{filename}")
    async def delete_draft_asset(
        document_id: str,
        filename: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.delete_draft_asset(
                actor,
                document_id,
                filename,
                correlation_id_value,
            )
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

    @app.post("/api/documents/{document_id}/draft/asset-ref")
    async def suggest_asset_ref(
        document_id: str,
        filename: str = "",
        alt_text: str = "",
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.suggest_asset_ref(actor, document_id, filename, alt_text)
        except Exception as exc:
            raise handle_errors(exc) from exc

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

