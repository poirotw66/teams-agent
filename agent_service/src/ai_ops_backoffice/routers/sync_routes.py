from __future__ import annotations

from fastapi import BackgroundTasks, Depends, FastAPI, Header

from ..faq_domain.errors import FaqValidationError
from ..request_models import SyncJobActionRequest, SyncJobCreateRequest
from .sync_owner_resolve import resolve_sync_owner_unit_id


def register_sync_routes(
    app: FastAPI,
    *,
    resolved_settings,
    sync_service,
    run_sync_job,
    current_actor,
    require_capability,
    faq_service=None,
    query_service=None,
) -> None:
    register_sync_read_routes(
        app,
        sync_service=sync_service,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_sync_write_routes(
        app,
        resolved_settings=resolved_settings,
        sync_service=sync_service,
        run_sync_job=run_sync_job,
        current_actor=current_actor,
        require_capability=require_capability,
        faq_service=faq_service,
        query_service=query_service,
    )


def register_sync_read_routes(
    app: FastAPI,
    *,
    sync_service,
    current_actor,
    require_capability,
) -> None:
    @app.get("/api/sync-jobs")
    async def list_sync_jobs(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.sync.read")
        items = sync_service.list_jobs(actor=actor)
        return {"items": items, "total": len(items)}

    @app.get("/api/sync-jobs/{job_id}")
    async def get_sync_job(job_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.sync.read")
        return sync_service.detail(job_id, actor=actor)


def register_sync_write_routes(
    app: FastAPI,
    *,
    resolved_settings,
    sync_service,
    run_sync_job,
    current_actor,
    require_capability,
    faq_service=None,
    query_service=None,
) -> None:
    @app.post("/api/sync-jobs")
    async def create_sync_job(
        payload: SyncJobCreateRequest,
        background_tasks: BackgroundTasks,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.sync.write")
        if payload.scope_type in {"FAQ", "DOCUMENT"} and not payload.scope_ids:
            raise FaqValidationError("selected sync scopes require scope_ids")
        owner_unit_id = await resolve_sync_owner_unit_id(
            payload=payload,
            actor=actor,
            resolved_settings=resolved_settings,
            faq_service=faq_service,
            query_service=query_service,
        )
        created = sync_service.create(
            scope_type=payload.scope_type,
            scope_ids=payload.scope_ids,
            owner_unit_id=owner_unit_id,
            reason=payload.reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        background_tasks.add_task(run_sync_job, created["job"]["job_id"])
        return created

    @app.post("/api/sync-jobs/{job_id}/retry")
    async def retry_sync_job(
        job_id: str,
        payload: SyncJobActionRequest,
        background_tasks: BackgroundTasks,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.sync.write")
        created = sync_service.retry(
            job_id,
            reason=payload.reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        background_tasks.add_task(run_sync_job, created["job"]["job_id"])
        return created

    @app.post("/api/sync-jobs/{job_id}/cancel")
    async def cancel_sync_job(
        job_id: str,
        payload: SyncJobActionRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.sync.write")
        if payload.expected_etag is None:
            raise FaqValidationError("expected_etag is required for cancellation")
        return sync_service.cancel(
            job_id,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            actor=actor,
        )
