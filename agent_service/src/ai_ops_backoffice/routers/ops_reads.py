from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from agent_service.operations.access import CAPABILITIES
from agent_service.usage import list_model_rates_usd

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
    example_service=None,
    quality_service=None,
    sync_service=None,
    budget_service=None,
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
        source: str | None = None,
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
            source=source,
            force_refresh=refresh,
        )
        filter_details = {
            "days": days,
            "preset": preset,
            "startDate": start_date,
            "endDate": end_date,
            "cursor": cursor,
            "actorRef": actor_ref,
            "userId": user_id,
            "issueTypeId": issue_type_id,
            "route": route,
            "conversationId": conversation_id,
            "model": model,
            "hasFeedback": has_feedback,
            "handoff": handoff,
            "channelScope": channel_scope,
            "query": query,
            "source": source,
            "resultCount": len(result.get("items", [])),
        }
        await audit_read(
            actor,
            "query.conversations",
            "conversations",
            after={k: v for k, v in filter_details.items() if v is not None},
        )
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
        owner_unit_id: str | None = None,
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
            owner_unit_id=owner_unit_id,
            force_refresh=refresh,
        )
        await audit_read(
            actor,
            "query.issues_summary",
            "issues_summary",
            after={
                "days": days,
                "preset": preset,
                "query": query,
                "ownerUnitId": owner_unit_id,
                "resultCount": len(result.get("items") or []),
            },
        )
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
        route: str | None = None,
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
            route=route,
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

    @app.get("/api/costs/rates")
    async def costs_rates(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.cost.read")
        pricing_svc = getattr(query_service, "pricing_service", None)
        if pricing_svc is not None:
            rates = pricing_svc.list_rates()
            exchange_rate = pricing_svc.get_exchange_rate()
            pricing_version = pricing_svc.get_pricing_version()
        else:
            rates = list_model_rates_usd()
            exchange_rate = float(query_service._metrics.get("usdTwdExchangeRate", 31.70))
            pricing_version = query_service._metrics.get("pricingVersion", "v1")
        return {
            "rates": rates,
            "exchangeRate": exchange_rate,
            "exchangeRateUsdToTwd": exchange_rate,
            "pricingVersion": pricing_version,
        }

    @app.get("/api/costs/rates/history")
    async def costs_rates_history(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.cost.read")
        pricing_svc = getattr(query_service, "pricing_service", None)
        if pricing_svc is not None:
            result = pricing_svc.list_history()
        else:
            result = {
                "currentPricingVersion": "v1",
                "currentExchangeRate": 31.70,
                "history": [],
                "audits": [],
            }
        await audit_read(actor, "query.costs_rates_history", "pricing_rules")
        return result

    @app.post("/api/costs/rates")
    async def update_costs_rate(
        payload: dict[str, Any],
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.cost.write")
        pricing_svc = getattr(query_service, "pricing_service", None)
        if pricing_svc is None:
            raise HTTPException(status_code=500, detail="Pricing service not configured")
        rate_type = str(payload.get("type") or "MODEL_RATE").upper()
        reason = payload.get("reason")
        effective_at_raw = payload.get("effectiveAt")
        effective_at = datetime.fromisoformat(effective_at_raw) if effective_at_raw else None
        pricing_version = payload.get("pricingVersion")
        if rate_type == "MODEL_RATE":
            model = str(payload.get("model") or "")
            input_rate = float(
                payload.get("inputUsdPer1MTokens")
                if payload.get("inputUsdPer1MTokens") is not None
                else payload.get("inputPerMillion", 0.0)
            )
            output_rate = float(
                payload.get("outputUsdPer1MTokens")
                if payload.get("outputUsdPer1MTokens") is not None
                else payload.get("outputPerMillion", 0.0)
            )
            result = await pricing_svc.update_model_rate(
                model=model,
                input_rate=input_rate,
                output_rate=output_rate,
                effective_at=effective_at,
                reason=reason,
                pricing_version=pricing_version,
                actor=actor,
            )
        elif rate_type == "EXCHANGE_RATE":
            exchange_rate = float(payload.get("exchangeRate", 0.0))
            result = await pricing_svc.update_exchange_rate(
                exchange_rate=exchange_rate,
                effective_at=effective_at,
                reason=reason,
                pricing_version=pricing_version,
                actor=actor,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported rate type: {rate_type}")
        return result

    @app.get("/api/health/summary")
    async def health_summary(
        date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.health.read")
        return await query_service.health_summary(target_date=date)

    @app.get("/api/audit-events")
    async def audit_events(
        actor_id: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.audit.read")
        items, next_cursor = await query_service.audit_store.list_events(
            cursor=cursor,
            limit=limit,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            start_date=start_date,
            end_date=end_date,
        )
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
        model: str | None = None,
        route: str | None = None,
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
            model=model,
            route=route,
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
        format_type: str | None = None,
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
            format_type=format_type,
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
                "formatType": format_type,
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

    @app.get("/api/admin/retention/status")
    async def retention_status(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        policy_info = (
            governance_service.peek_runtime_retention("operational-events")
            if governance_service
            else None
        )
        return {
            "policy": policy_info or {"policyId": "operational-events", "ttlDays": 365, "status": "ACTIVE"},
            "domains": {
                "operationalEvents": {
                    "retentionDays": 365,
                    "retentionStart": "occurred_at",
                    "description": "Operational event log TTL",
                },
                "exportJobs": {
                    "retentionDays": 30,
                    "retentionStart": "created_at / finished_at",
                    "description": "Export job artifacts TTL",
                },
                "examples": {
                    "retentionDays": 365,
                    "retentionStart": "retired_at (RETIRED) or updated_at (REJECTED)",
                    "description": "Few-shot examples domain",
                },
                "quality": {
                    "retentionDays": 365,
                    "retentionStart": "updated_at (candidates), resolved_at (cases), created_at (clusters)",
                    "description": "Quality cases, candidates, and clusters",
                },
                "sync": {
                    "retentionDays": 365,
                    "retentionStart": "finished_at or requested_at (COMPLETED, FAILED, CANCELLED)",
                    "description": "Knowledge sync jobs and checkpoints",
                },
                "budget": {
                    "retentionDays": 365,
                    "retentionStart": "resolved_at (alerts), updated_at (deliveries), expires_at (policies)",
                    "description": "Budget alerts, delivery attempts, and expired policies",
                },
            },
            "dataStates": [
                {"code": "UNAUTHORIZED", "label": "未授權", "description": "使用者無權限存取該領域或部門範疇之資料"},
                {"code": "MASKED", "label": "已遮罩", "description": "敏感個資與金鑰依脫敏規則遮蔽 [REDACTED]"},
                {"code": "UNMASKED_WITH_REASON", "label": "有理由未遮罩", "description": "具備稽核權限並具體填寫理由申請查閱未遮罩明細，已記錄稽核紀錄"},
                {"code": "EXPIRED_OR_PURGED", "label": "已過期／清除", "description": "超過資料保存期限或已被排程安全清除"},
            ],
        }

    @app.post("/api/admin/retention/purge")
    async def purge_retention(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        events_res = await query_service.purge_expired_events()
        events_removed = events_res.get("removed", 0)

        export_removed = 0
        if hasattr(query_service, "export_jobs") and query_service.export_jobs:
            try:
                export_removed = await query_service.export_jobs.purge_expired_jobs()
            except Exception:
                pass

        examples_res = example_service.purge_expired(actor=actor) if example_service else {"removed": 0}
        examples_removed = examples_res.get("removed", 0)

        quality_res = quality_service.purge_expired(actor=actor) if quality_service else {"total": 0}
        quality_removed = quality_res.get("total", 0)

        sync_res = sync_service.purge_expired(actor=actor) if sync_service else {"total": 0}
        sync_removed = sync_res.get("total", 0)

        budget_res = budget_service.purge_expired(actor=actor) if budget_service else {"total": 0}
        budget_removed = budget_res.get("total", 0)

        total_removed = (
            events_removed
            + export_removed
            + examples_removed
            + quality_removed
            + sync_removed
            + budget_removed
        )

        result = {
            "removed": events_removed,
            "operationalEvents": events_removed,
            "exportJobs": export_removed,
            "examples": examples_removed,
            "quality": quality_removed,
            "sync": sync_removed,
            "budget": budget_removed,
            "totalRemoved": total_removed,
        }
        await audit_read(actor, "retention.purge", "all_domains", after=result)
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

