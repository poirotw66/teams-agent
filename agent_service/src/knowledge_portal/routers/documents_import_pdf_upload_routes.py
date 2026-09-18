"""PDF upload and PDF-job status routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)

from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_import_pdf_upload_routes(
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
    del settings

    @app.post("/api/documents/import-pdf")
    async def import_pdf(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        async_mode: str = "auto",
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
        idempotency_key_value: str | None = Depends(idempotency_key),
    ):
        payload = await file.read()
        try:
            return await service.import_pdf_smart(
                actor,
                payload,
                filename=file.filename,
                async_mode=async_mode,
                job_store=pdf_job_store,
                background_tasks=background_tasks,
                correlation_id=correlation_id_value,
                idempotency_key=idempotency_key_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/pdf-jobs/{job_id}")
    async def get_pdf_job(
        job_id: str,
        background_tasks: BackgroundTasks,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        job = pdf_job_store.get(job_id)
        if job is None or (job.actor_id and job.actor_id != actor.user_id):
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "PDF job not found"},
            )
        resume = getattr(pdf_job_store, "resume", None)
        if resume is not None:
            resume(job, background_tasks)
        return pdf_job_store.to_public_dict(job)
