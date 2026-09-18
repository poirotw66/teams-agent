"""Draft asset mutation routes for Knowledge Portal documents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService


def register_documents_draft_asset_mutation_routes(
    app: FastAPI,
    *,
    service: PortalService,
    authorize: Callable[..., None],
    current_actor: Callable[..., PortalActor],
    correlation_id: Callable[..., str],
    handle_errors: Callable[[Exception], HTTPException],
    **_: Any,
) -> None:
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
