"""Domain query mixin: ExportsQueryMixin."""

from __future__ import annotations

from typing import Any

from agent_service.operations.access import ActorContext
from .export_format import wrap_export_payload

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
    ) -> dict[str, Any]:
        period_kwargs = {
            "preset": preset,
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
        }
        period = self._resolve_period(**period_kwargs)
        query_filters = {
            key: value
            for key, value in {
                "actorRef": actor_ref,
                "issueTypeId": issue_type_id,
                "route": route,
                "conversationId": conversation_id,
                "model": model,
                "hasFeedback": has_feedback,
                "handoff": handoff,
                "rating": rating,
                "reason": feedback_reason,
                "resolvedStatus": resolved_status,
                "channelScope": channel_scope,
            }.items()
            if value is not None
        }
        request_params = {
            "period": period_kwargs,
            "queryFilters": {
                "actor_ref": actor_ref,
                "issue_type_id": issue_type_id,
                "route": route,
                "conversation_id": conversation_id,
                "model": model,
                "has_feedback": has_feedback,
                "handoff": handoff,
                "rating": rating,
                "feedback_reason": feedback_reason,
                "resolved_status": resolved_status,
                "channel_scope": channel_scope,
            },
            "reason": reason,
        }
        self.export_jobs.configure_execution_backend(self)
        job = await self.export_jobs.create_job(
            actor=actor,
            export_type=export_type,
            reason=reason,
            days=days,
            request_params=request_params,
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
        export_type = job.export_type
        if export_type == "operations_summary":
            data = await self.operations_summary(actor, **period_kwargs)
        elif export_type == "issues_summary":
            data = await self.issues_summary(actor, **period_kwargs)
        elif export_type == "costs_summary":
            data = await self.costs_summary(
                actor,
                **period_kwargs,
                model=filters.get("model"),
            )
        elif export_type == "feedback":
            data = await self.list_feedback(
                actor,
                **period_kwargs,
                rating=filters.get("rating"),
                issue_type_id=filters.get("issue_type_id"),
                reason=filters.get("feedback_reason"),
                resolved_status=filters.get("resolved_status"),
                handoff=filters.get("handoff"),
                limit=self._settings.export_max_records + 1,
            )
        elif export_type == "routes_summary":
            data = await self.routes_summary(
                actor,
                **period_kwargs,
                issue_type_id=filters.get("issue_type_id"),
            )
        elif export_type == "knowledge_performance":
            data = await self.list_documents(
                actor,
                preset=period_kwargs.get("preset"),
                days=period_kwargs.get("days") or job.days,
                limit=self._settings.export_max_records + 1,
            )
        elif export_type == "conversations":
            data = await self.list_conversations(
                actor,
                **period_kwargs,
                limit=self._settings.export_max_records + 1,
                actor_ref=filters.get("actor_ref"),
                user_id=filters.get("user_id"),
                issue_type_id=filters.get("issue_type_id"),
                route=filters.get("route"),
                conversation_id=filters.get("conversation_id"),
                model=filters.get("model"),
                has_feedback=filters.get("has_feedback"),
                handoff=filters.get("handoff"),
                channel_scope=filters.get("channel_scope"),
            )
        else:
            raise ValueError(f"Unsupported export type: {export_type}")
        query_filters = {
            key: value
            for key, value in {
                "actorRef": filters.get("actor_ref"),
                "userId": filters.get("user_id"),
                "issueTypeId": filters.get("issue_type_id"),
                "route": filters.get("route"),
                "conversationId": filters.get("conversation_id"),
                "model": filters.get("model"),
                "hasFeedback": filters.get("has_feedback"),
                "handoff": filters.get("handoff"),
                "rating": filters.get("rating"),
                "reason": filters.get("feedback_reason"),
                "resolvedStatus": filters.get("resolved_status"),
                "channelScope": filters.get("channel_scope"),
            }.items()
            if value is not None
        }
        return wrap_export_payload(
            data,
            export_type=export_type,
            reason=reason,
            requested_by=actor.user_id,
            requested_role=actor.role,
            export_format=job.export_format,
            period=period,
            pricing_version=self._metrics.get("pricingVersion"),
            query_filters=query_filters,
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

