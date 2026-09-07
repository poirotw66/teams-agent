from __future__ import annotations

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from agent_service.operations.access import CAPABILITIES

from ..auth import header_auth_allowed
from ..knowledge_bridge.capabilities import knowledge_capabilities_for
from ..request_models import ExportRequest
from ..services.query_audit import record_query_audit
from ..services.rate_limit import RateLimitExceeded
from ..services.reconciliation import (
    reconcile_costs_summary,
    reconcile_issues_summary,
    reconcile_operations_summary,
)

ALLOWED_EXPORT_FORMATS = frozenset({"json", "csv", "xlsx"})
EXPORT_CAPABILITIES = {
    "operations_summary": "ops.summary.read",
    "issues_summary": "ops.issues.read",
    "costs_summary": "ops.cost.read",
    "feedback": "ops.feedback.read",
    "routes_summary": "ops.issues.read",
    "knowledge_performance": "ops.knowledge.read",
    "conversations": "ops.conversations.read",
}


def register_ops_read_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    governance_service,
    current_actor,
    require_capability,
    audit_read,
    export_rate_limiter,
) -> None:
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/auth/config")
    async def auth_config() -> dict[str, object]:
        return {
            "authMode": resolved_settings.auth_mode,
            "headerAuthAllowed": (
                resolved_settings.auth_mode != "ENTRA" and header_auth_allowed()
            ),
        }

    @app.get("/api/capabilities")
    async def capabilities(actor=Depends(current_actor)) -> dict[str, object]:
        knowledge_caps = sorted(knowledge_capabilities_for(actor))
        return {
            "userId": actor.user_id,
            "userName": actor.display_name or actor.user_id,
            "displayName": actor.display_name or actor.user_id,
            "role": actor.role,
            "capabilities": sorted(CAPABILITIES.get(actor.role, frozenset())),
            "knowledgeCapabilities": knowledge_caps,
            "ownerUnitIds": list(actor.owner_unit_ids),
            "knowledgePortalUrl": resolved_settings.knowledge_portal_url,
            "knowledgeBridgeEnabled": bool(
                resolved_settings.knowledge_bridge_enabled
                and resolved_settings.knowledge_delegation_secret
            ),
            "knowledgeUiUrl": "/knowledge-ui/#/knowledge",
            "authMode": resolved_settings.auth_mode,
            "deploymentTenantId": resolved_settings.deployment_tenant_id,
            "relaxedWorkflow": resolved_settings.relaxed_workflow,
            "minTestCasesForReview": resolved_settings.min_test_cases_for_review,
        }

    @app.get("/api/taxonomy")
    async def taxonomy(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        return {
            "taxonomyVersion": query_service.taxonomy.version,
            "items": [item.model_dump() for item in query_service.taxonomy.list_active()],
        }

    @app.get("/api/metrics/definitions")
    async def metrics_definitions(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        return query_service.metrics_definitions()

    @app.get("/api/operations/summary")
    async def operations_summary(
        days: int = Query(default=7, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        model: str | None = None,
        issue_type_id: str | None = None,
        interval: str = Query(default="DAY"),
        refresh: bool = False,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        result = await query_service.operations_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            model=model,
            issue_type_id=issue_type_id,
            interval=interval,
            force_refresh=refresh,
        )
        project = (resolved_settings.gcp_project_id or "").lower()
        environment = "prod" if "prod" in project else "lab"
        cost_flag = governance_service.peek_runtime_flag(
            "cost_display", environment=environment
        )
        cost_enabled = True
        if cost_flag is not None:
            cost_enabled = str(cost_flag.get("value") or "").lower() in {
                "true",
                "1",
                "enabled",
            }
        if not cost_enabled:
            result = {
                **result,
                "estimatedCostUsd": None,
                "costCoverage": None,
                "costDisplayEnabled": False,
            }
        else:
            result = {**result, "costDisplayEnabled": True}
        await audit_read(
            actor,
            "query.operations_summary",
            "operations_summary",
            after={
                "days": days,
                "preset": preset,
                "startDate": start_date,
                "endDate": end_date,
                "model": model,
                "issueTypeId": issue_type_id,
                "interval": interval,
            },
        )
        return result

    @app.get("/api/aggregates/summary")
    async def aggregates_summary(
        days: int = Query(default=7, ge=1, le=365),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        result = await query_service.daily_aggregates_summary(actor, days=days)
        await audit_read(
            actor,
            "query.aggregates_summary",
            "daily_aggregates",
            after={"days": days},
        )
        return result

    @app.post("/api/aggregates/rebuild")
    async def aggregates_rebuild(
        days: int = Query(default=30, ge=1, le=365),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        result = await query_service.rebuild_daily_aggregates(days=days)
        await audit_read(
            actor,
            "query.aggregates_rebuild",
            "daily_aggregates",
            after={"days": days, "written": result.get("written")},
        )
        return result

    @app.get("/api/conversations")
    async def conversations(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        cursor: str | None = None,
        actor_ref: str | None = None,
        user_id: str | None = None,
        issue_type_id: str | None = None,
        route: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
        has_feedback: bool | None = None,
        handoff: bool | None = None,
        channel_scope: str | None = None,
        query: str | None = None,
        refresh: bool = False,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.conversations.read")
        result = await query_service.list_conversations(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            cursor=cursor,
            actor_ref=actor_ref,
            user_id=user_id,
            issue_type_id=issue_type_id,
            route=route,
            conversation_id=conversation_id,
            model=model,
            has_feedback=has_feedback,
            handoff=handoff,
            channel_scope=channel_scope,
            query=query,
            force_refresh=refresh,
        )
        await audit_read(actor, "query.conversations", "conversations")
        return result

    @app.get("/api/conversations/{conversation_id}")
    async def conversation_detail(
        conversation_id: str,
        unmask_reason: str | None = None,
        refresh: bool = False,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.conversations.read")
        if unmask_reason and not actor.has_capability("ops.conversations.unmasked"):
            raise HTTPException(status_code=403, detail="Unmasked conversation access is forbidden.")
        if unmask_reason and len(unmask_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="unmask_reason must be at least 3 characters.")
        detail = await query_service.conversation_detail(
            actor,
            conversation_id,
            unmask_reason=unmask_reason,
            force_refresh=refresh,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        action = (
            "query.conversation_unmasked"
            if detail.get("unmaskAuthorized")
            else "query.conversation_detail"
        )
        await audit_read(
            actor,
            action,
            conversation_id,
            after={"unmaskReason": unmask_reason} if unmask_reason else None,
        )
        return detail

    @app.get("/api/issues/summary")
    async def issues_summary(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        query: str | None = None,
        refresh: bool = False,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        result = await query_service.issues_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            query=query,
            force_refresh=refresh,
        )
        await audit_read(actor, "query.issues_summary", "issues_summary")
        return result

    @app.get("/api/issues/{issue_type_id}/routes")
    async def issue_routes(
        issue_type_id: str,
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        result = await query_service.issue_routes(
            actor,
            issue_type_id,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(actor, "query.issue_routes", issue_type_id)
        return result

    @app.get("/api/routes/summary")
    async def routes_summary(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
        refresh: bool = False,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        result = await query_service.routes_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            issue_type_id=issue_type_id,
            force_refresh=refresh,
        )
        await audit_read(actor, "query.routes_summary", "routes_summary")
        return result

    @app.get("/api/costs/summary")
    async def costs_summary(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        model: str | None = None,
        refresh: bool = False,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.cost.read")
        result = await query_service.costs_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            model=model,
            force_refresh=refresh,
        )
        await audit_read(
            actor,
            "query.costs_summary",
            "costs_summary",
            after={
                "days": days,
                "preset": preset,
                "startDate": start_date,
                "endDate": end_date,
                "model": model,
            },
        )
        return result

    @app.get("/api/health/summary")
    async def health_summary(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.health.read")
        return await query_service.health_summary()

    @app.get("/api/audit-events")
    async def audit_events(
        cursor: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.audit.read")
        items, next_cursor = await query_service.audit_store.list_events(cursor=cursor)
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "nextCursor": next_cursor,
            "hasMore": next_cursor is not None,
        }

    @app.get("/api/feedback")
    async def feedback_list(
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        rating: str | None = None,
        issue_type_id: str | None = None,
        reason: str | None = None,
        resolved_status: str | None = Query(default=None, alias="resolved"),
        handoff: bool | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.feedback.read")
        return await query_service.list_feedback(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            rating=rating,
            issue_type_id=issue_type_id,
            reason=reason,
            resolved_status=resolved_status,
            handoff=handoff,
            limit=limit,
            cursor=cursor,
        )

    @app.get("/api/admin/reconciliation/operations-summary")
    async def reconciliation_operations_summary(
        days: int = Query(default=7, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        result = await reconcile_operations_summary(
            query_service,
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(
            actor,
            "reconciliation.operations_summary",
            "operations_summary",
            after={"allMatch": result["allMatch"]},
        )
        return result

    @app.get("/api/admin/reconciliation/costs-summary")
    async def reconciliation_costs_summary(
        days: int = Query(default=7, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        result = await reconcile_costs_summary(
            query_service,
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(
            actor,
            "reconciliation.costs_summary",
            "costs_summary",
            after={"allMatch": result["allMatch"]},
        )
        return result

    @app.get("/api/admin/reconciliation/issues-summary")
    async def reconciliation_issues_summary(
        days: int = Query(default=7, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        result = await reconcile_issues_summary(
            query_service,
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(
            actor,
            "reconciliation.issues_summary",
            "issues_summary",
            after={"allMatch": result["allMatch"]},
        )
        return result

    @app.get("/api/knowledge")
    async def knowledge_documents(
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.knowledge.read")
        result = await query_service.list_documents(
            actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
            preset=preset,
            days=days,
            limit=limit,
            cursor=cursor,
        )
        await audit_read(
            actor,
            "knowledge.documents.list",
            "knowledge_documents",
            after={
                "status": status,
                "ownerUnitId": owner_unit_id,
                "resultCount": len(result["items"]),
            },
        )
        return result

    @app.get("/api/knowledge/{document_id}/performance")
    async def knowledge_performance(
        document_id: str,
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        cursor: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.knowledge.read")
        return await query_service.document_performance(
            actor,
            document_id,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            issue_type_id=issue_type_id,
            limit=limit,
            cursor=cursor,
        )

    @app.post("/api/admin/retention/purge")
    async def purge_retention(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        result = await query_service.purge_expired_events()
        await audit_read(actor, "retention.purge", "operational_events", after=result)
        return result

    @app.post("/api/exports")
    async def create_export(payload: ExportRequest, actor=Depends(current_actor)) -> dict[str, object]:
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
        idempotency = payload.idempotency_key
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
                idempotency_key=idempotency,
                channel_scope=payload.channel_scope,
            )
        except Exception as exc:
            from ai_ops_backoffice.services.export_authorization import (
                ExportIdempotencyConflictError,
            )

            if isinstance(exc, ExportIdempotencyConflictError):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise

    @app.get("/api/exports/{job_id}")
    async def get_export(job_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.exports.read")
        job = await query_service.get_export_job(job_id, actor=actor)
        if job is None:
            raise HTTPException(status_code=404, detail="Export job not found.")
        return job

    @app.get("/api/exports/{job_id}/download")
    async def download_export(job_id: str, actor=Depends(current_actor)) -> Response:
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
            from ai_ops_backoffice.services.export_authorization import ExportAuthorizationError

            if isinstance(exc, ExportAuthorizationError):
                raise HTTPException(status_code=404, detail="Export job not found.") from exc
            raise
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

