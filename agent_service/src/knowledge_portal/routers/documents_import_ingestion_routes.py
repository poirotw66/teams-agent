"""Ingestion job status / cancel / Cloud Tasks worker routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException

from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_import_ingestion_routes(
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
    del service, correlation_id, idempotency_key

    @app.get("/api/ingestion-jobs/{job_id}")
    @app.get("/api/v1/ingestion-jobs/{job_id}")
    async def get_ingestion_job(
        job_id: str,
        background_tasks: BackgroundTasks,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        job = pdf_job_store.get(job_id)
        if job is None or (job.actor_id and job.actor_id != actor.user_id):
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Ingestion job not found"},
            )
        resume = getattr(pdf_job_store, "resume", None)
        if resume is not None:
            resume(job, background_tasks)
        return pdf_job_store.to_public_dict(job)

    @app.post("/api/ingestion-jobs/{job_id}/cancel")
    @app.post("/api/v1/ingestion-jobs/{job_id}/cancel")
    async def cancel_ingestion_job(
        job_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            job = pdf_job_store.cancel(job_id, actor_id=actor.user_id)
            return pdf_job_store.to_public_dict(job)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/internal/v1/ingestion-jobs/{job_id}/run")
    async def run_ingestion_job(
        job_id: str,
        x_cloudtasks_taskname: str | None = Header(
            default=None,
            alias="X-CloudTasks-TaskName",
        ),
    ):
        queue = settings.ingestion_tasks_queue
        expected_prefix = f"{queue}/tasks/" if queue else ""
        if (
            not expected_prefix
            or not x_cloudtasks_taskname
            or not x_cloudtasks_taskname.startswith(expected_prefix)
        ):
            raise HTTPException(status_code=404, detail="Not found.")
        runner = getattr(pdf_job_store, "run", None)
        if runner is None:
            raise HTTPException(status_code=503, detail="Cloud worker is unavailable.")
        await runner(job_id)
        return {"status": "accepted", "jobId": job_id}
