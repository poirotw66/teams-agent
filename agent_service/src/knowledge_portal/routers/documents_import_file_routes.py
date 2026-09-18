"""Markdown / DOCX document import routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_import_file_routes(
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
    del settings, pdf_job_store, correlation_id, idempotency_key

    @app.post("/api/documents/import-markdown")
    async def import_markdown(
        file: UploadFile = File(...),
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            raw = (await file.read()).decode("utf-8")
            return service.import_markdown(actor, raw, filename=file.filename)
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_UTF8",
                    "message": "Markdown file must use UTF-8 encoding.",
                },
            ) from exc
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/import-docx")
    async def import_docx(
        file: UploadFile = File(...),
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return service.import_docx(
                actor,
                await file.read(),
                filename=file.filename,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc
