"""Export job create, status, and download routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response

from ...request_models import ExportRequest
from .constants import ALLOWED_EXPORT_FORMATS, EXPORT_CAPABILITIES
from .context import AnalyticsRouteContext


async def _create_export_job(
    *,
    query_service: Any,
    payload: ExportRequest,
    actor: Any,
) -> dict[str, object]:
    try:
        return await query_service.create_export_job(
            actor=actor,
            export_type=payload.export_type,
            reason=payload.reason,
            days=payload.days,
            export_format=payload.export_format,
            preset=payload.preset,
            start_date=payload.start_date,
            end_date=payload.end_date,
            actor_ref=payload.actor_ref,
            issue_type_id=payload.issue_type_id,
            route=payload.route,
            conversation_id=payload.conversation_id,
            model=payload.model,
            has_feedback=payload.has_feedback,
            handoff=payload.handoff,
            rating=payload.rating,
            feedback_reason=payload.feedback_reason,
            resolved_status=payload.resolved_status,
            idempotency_key=payload.idempotency_key,
            channel_scope=payload.channel_scope,
            query=payload.query,
            source=payload.source,
            status=payload.status,
            owner_unit_id=payload.owner_unit_id,
            format_type=payload.format_type,
        )
    except Exception as exc:
        from ai_ops_backoffice.services.export_authorization import (
            ExportIdempotencyConflictError,
        )

        if isinstance(exc, ExportIdempotencyConflictError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise


def register_export_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    export_rate_limiter = ctx.export_rate_limiter

    @app.post("/api/exports")
    async def create_export(
        payload: ExportRequest,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.exports.create")
        export_capability = EXPORT_CAPABILITIES.get(payload.export_type)
        if export_capability is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported export type: {payload.export_type}",
            )
        require_capability(actor, export_capability)
        if payload.export_format not in ALLOWED_EXPORT_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported export format: {payload.export_format}",
            )
        export_rate_limiter.check(actor.user_id)
        return await _create_export_job(
            query_service=query_service,
            payload=payload,
            actor=actor,
        )

    @app.get("/api/exports/{job_id}")
    async def get_export(
        job_id: str,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.exports.read")
        job = await query_service.get_export_job(job_id, actor=actor)
        if job is None:
            raise HTTPException(status_code=404, detail="Export job not found.")
        return job

    @app.get("/api/exports/{job_id}/download")
    async def download_export(
        job_id: str,
        actor: Any = Depends(current_actor),
    ) -> Response:
        require_capability(actor, "ops.exports.read")
        job = await query_service.export_jobs.get_job(job_id, actor=actor)
        if job is None:
            raise HTTPException(status_code=404, detail="Export job not found.")
        if job.status != "COMPLETED":
            raise HTTPException(status_code=409, detail="Export job is not completed.")
        export_format = job.export_format or "json"
        artifact = await query_service.export_jobs.get_content(job)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Export content is not available.")
        content, media_type = artifact
        filename = f"{job_id}.{export_format}"
        try:
            await query_service.export_jobs.record_download(job_id, actor=actor)
        except Exception as exc:
            from ai_ops_backoffice.services.export_authorization import (
                ExportAuthorizationError,
            )

            if isinstance(exc, ExportAuthorizationError):
                raise HTTPException(status_code=404, detail="Export job not found.") from exc
            raise
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
