"""Domain query mixin: ExportsQueryMixin."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext

from .export_format import wrap_export_payload
from .query_exports_create import build_export_create_filters
from .query_exports_execute import export_query_filters, fetch_export_data

__all__ = [
    "ExportQueryService",
    "ExportsQueryMixin",
]


class ExportsQueryMixin:
    async def create_export_job(
        self,
        *,
        actor: ActorContext,
        export_type: str,
        reason: str,
        days: int,
        export_format: str = "json",
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor_ref: str | None = None,
        issue_type_id: str | None = None,
        route: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
        has_feedback: bool | None = None,
        handoff: bool | None = None,
        rating: str | None = None,
        feedback_reason: str | None = None,
        resolved_status: str | None = None,
        idempotency_key: str | None = None,
        channel_scope: str | None = None,
        query: str | None = None,
        source: str | None = None,
        status: str | None = None,
        owner_unit_id: str | None = None,
        format_type: str | None = None,
    ) -> dict[str, Any]:
        period_kwargs = {
            "preset": preset, "days": days, "start_date": start_date, "end_date": end_date,
        }
        period = self._resolve_period(**period_kwargs)
        snake_filters, query_filters = build_export_create_filters(
            actor_ref=actor_ref,
            issue_type_id=issue_type_id,
            route=route,
            conversation_id=conversation_id,
            model=model,
            has_feedback=has_feedback,
            handoff=handoff,
            rating=rating,
            feedback_reason=feedback_reason,
            resolved_status=resolved_status,
            channel_scope=channel_scope,
            query=query,
            source=source,
            status=status,
            owner_unit_id=owner_unit_id,
            format_type=format_type,
        )
        self.export_jobs.configure_execution_backend(self)
        job = await self.export_jobs.create_job(
            actor=actor,
            export_type=export_type,
            reason=reason,
            days=days,
            request_params={
                "period": period_kwargs, "queryFilters": snake_filters, "reason": reason,
            },
            export_format=export_format,
            idempotency_key=idempotency_key,
            request_metadata={
                "queryFilters": query_filters,
                "periodPreset": period.preset,
                "periodStart": period.start_at.isoformat(),
                "periodEnd": period.end_at.isoformat(),
            },
        )
        return {
            "jobId": job.job_id,
            "status": job.status,
            "exportType": job.export_type,
            "exportFormat": job.export_format,
            "expiresAt": job.expires_at,
        }

    async def execute(self, *, actor: ActorContext, job: Any) -> dict[str, Any]:
        """ExportExecutionBackend: rebuild export using a freshly resolved actor."""
        params = dict(job.request_params or {})
        period_kwargs = dict(params.get("period") or {"days": job.days})
        filters = dict(params.get("queryFilters") or {})
        reason = str(params.get("reason") or job.reason)
        period = self._resolve_period(**period_kwargs)
        data = await fetch_export_data(
            self,
            actor=actor,
            export_type=job.export_type,
            period_kwargs=period_kwargs,
            filters=filters,
            job_days=job.days,
            export_max_records=self._settings.export_max_records,
        )
        return wrap_export_payload(
            data,
            export_type=job.export_type,
            reason=reason,
            requested_by=actor.user_id,
            requested_role=actor.role,
            export_format=job.export_format,
            period=period,
            pricing_version=self._metrics.get("pricingVersion"),
            query_filters=export_query_filters(filters),
        )

    async def get_export_job(self, job_id: str, *, actor: ActorContext) -> dict[str, Any] | None:
        """Return export job progress metadata only — never the artifact payload.

        Full export content is available solely through the re-authorized,
        audited download path.
        """
        job = await self.export_jobs.get_job(job_id, actor=actor)
        if job is None:
            return None
        return {
            "jobId": job.job_id,
            "status": job.status,
            "exportType": job.export_type,
            "exportFormat": job.export_format,
            "reason": job.reason,
            "attemptCount": job.attempt_count,
            "maxAttempts": job.max_attempts,
            "error": job.error,
            "createdAt": job.created_at,
            "expiresAt": job.expires_at,
            "completedAt": job.completed_at,
            "hasArtifact": bool(
                job.content_ref or job.download_bytes is not None or job.download_content
            ),
        }


ExportQueryService = ExportsQueryMixin

