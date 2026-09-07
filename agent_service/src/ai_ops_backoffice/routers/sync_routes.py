from __future__ import annotations

import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, Header

from ..request_models import SyncJobActionRequest, SyncJobCreateRequest


def register_sync_routes(
    app: FastAPI,
    *,
    resolved_settings,
    sync_service,
    run_sync_job,
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
        owner_unit_id = resolved_settings.default_owner_unit_id
        if payload.scope_type == "FAQ":
            owners = set()
            for faq_id in payload.scope_ids:
                detail = faq_service.detail(faq_id=faq_id, actor=actor)
                owners.add(detail["versions"][-1]["content"]["owner_unit_id"])
            if len(owners) != 1:
                raise FaqValidationError("FAQ sync scope must belong to one owner unit")
            owner_unit_id = next(iter(owners))
        elif payload.scope_type == "DOCUMENT":
            inventory = await query_service.list_documents(actor, limit=100)
            if inventory.get("portalStatus") != "available":
                raise HTTPException(status_code=503, detail="Knowledge inventory is unavailable.")
            selected = [
                item for item in inventory["items"] if item.get("documentId") in payload.scope_ids
            ]
            if len(selected) != len(set(payload.scope_ids)):
                raise FaqNotFoundError("one or more sync documents were not found")
            owners = {item.get("ownerUnitId") for item in selected}
            if None in owners or len(owners) != 1:
                raise FaqValidationError("document sync scope must belong to one owner unit")
            owner_unit_id = next(iter(owners))
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

