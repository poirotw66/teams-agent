from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent_service.operations.access import CAPABILITIES
from agent_service.operations.audit_errors import AuditWriteError

from .auth import BackofficeAuthError, header_auth_allowed, resolve_actor
from .services.periods import PeriodPolicyError
from .services.phase2_registry import FaqRecord, Phase2Registry, QualityCaseRecord, SyncJobRecord
from .services.phase3_registry import FeatureFlagRecord, Phase3Registry, PromptVersionRecord
from .services.query_audit import record_query_audit
from .services.query_service import BackofficeQueryService
from .services.rate_limit import ExportRateLimiter, RateLimitExceeded
from .services.reconciliation import (
    reconcile_costs_summary,
    reconcile_issues_summary,
    reconcile_operations_summary,
)
from .settings import BackofficeSettings

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
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


class ExportRequest(BaseModel):
    export_type: str = Field(default="operations_summary")
    reason: str = Field(min_length=3)
    days: int = Field(default=30, ge=1, le=186)
    export_format: str = Field(default="json")
    preset: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    actor_ref: str | None = None
    issue_type_id: str | None = None
    route: str | None = None
    conversation_id: str | None = None
    model: str | None = None
    has_feedback: bool | None = None
    handoff: bool | None = None
    rating: str | None = None
    feedback_reason: str | None = None
    resolved_status: str | None = None


class FaqCreateRequest(BaseModel):
    faq_key: str
    question: str
    answer: str
    owner_unit_id: str = "IT Service Desk"


class QualityCaseCreateRequest(BaseModel):
    title: str
    case_type: str
    owner_unit_id: str = "IT Service Desk"


class SyncJobCreateRequest(BaseModel):
    scope_type: str
    reason: str = Field(min_length=3)


class PromptCandidateRequest(BaseModel):
    prompt_id: str
    change_reason: str
    template_summary: str


def create_app(settings: BackofficeSettings | None = None) -> FastAPI:
    resolved_settings = settings or BackofficeSettings.from_env()
    query_service = BackofficeQueryService(resolved_settings)
    export_rate_limiter = ExportRateLimiter()
    phase2 = Phase2Registry()
    phase3 = Phase3Registry()

    def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = resolved_settings.service_token
        if not expected:
            return
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid service token.")

    def current_actor(
        authorization: str | None = Header(default=None),
        x_backoffice_user_id: str | None = Header(default=None, alias="X-Backoffice-User-Id"),
        x_backoffice_user_name: str | None = Header(default=None, alias="X-Backoffice-User-Name"),
        x_backoffice_role: str | None = Header(default="ANALYST", alias="X-Backoffice-Role"),
        x_backoffice_owner_units: str | None = Header(default="", alias="X-Backoffice-Owner-Units"),
    ):
        try:
            return resolve_actor(
                auth_mode=resolved_settings.auth_mode,
                authorization=authorization,
                header_user_id=x_backoffice_user_id,
                header_user_name=x_backoffice_user_name,
                header_role=x_backoffice_role,
                header_owner_units=x_backoffice_owner_units,
                default_owner_unit_id=resolved_settings.default_owner_unit_id,
                entra_tenant_id=resolved_settings.entra_tenant_id,
                entra_client_id=resolved_settings.entra_client_id,
            )
        except BackofficeAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def require_capability(actor, capability: str) -> None:
        if not actor.has_capability(capability):
            raise HTTPException(status_code=403, detail="Forbidden.")

    async def audit_read(actor, action: str, target_id: str, after: dict[str, object] | None = None) -> None:
        await record_query_audit(
            query_service.audit_store,
            actor=actor,
            action=action,
            target_id=target_id,
            environment=query_service.environment,
            after=after,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.ops_store_path.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title="AI Operations Backoffice", lifespan=lifespan)

    @app.exception_handler(PeriodPolicyError)
    async def period_policy_handler(_request, exc: PeriodPolicyError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(_request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @app.exception_handler(AuditWriteError)
    async def audit_write_handler(_request, exc: AuditWriteError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

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
        return {
            "role": actor.role,
            "capabilities": sorted(CAPABILITIES.get(actor.role, frozenset())),
            "knowledgePortalUrl": resolved_settings.knowledge_portal_url,
            "authMode": resolved_settings.auth_mode,
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
        days: int = Query(default=7, ge=1, le=186),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.summary.read")
        result = await query_service.operations_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(
            actor,
            "query.operations_summary",
            "operations_summary",
            after={"days": days, "preset": preset, "startDate": start_date, "endDate": end_date},
        )
        return result

    @app.get("/api/conversations")
    async def conversations(
        days: int = Query(default=30, ge=1, le=186),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        cursor: str | None = None,
        actor_ref: str | None = None,
        issue_type_id: str | None = None,
        route: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
        has_feedback: bool | None = None,
        handoff: bool | None = None,
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
            issue_type_id=issue_type_id,
            route=route,
            conversation_id=conversation_id,
            model=model,
            has_feedback=has_feedback,
            handoff=handoff,
        )
        await audit_read(actor, "query.conversations", "conversations")
        return result

    @app.get("/api/conversations/{conversation_id}")
    async def conversation_detail(
        conversation_id: str,
        unmask_reason: str | None = None,
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
        days: int = Query(default=30, ge=1, le=186),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.issues.read")
        result = await query_service.issues_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(actor, "query.issues_summary", "issues_summary")
        return result

    @app.get("/api/issues/{issue_type_id}/routes")
    async def issue_routes(
        issue_type_id: str,
        days: int = Query(default=30, ge=1, le=186),
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
        days: int = Query(default=30, ge=1, le=186),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
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
        )
        await audit_read(actor, "query.routes_summary", "routes_summary")
        return result

    @app.get("/api/costs/summary")
    async def costs_summary(
        days: int = Query(default=30, ge=1, le=186),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.cost.read")
        result = await query_service.costs_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        await audit_read(actor, "query.costs_summary", "costs_summary")
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
        days: int = Query(default=30, ge=1, le=186),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        rating: str | None = None,
        reason: str | None = None,
        resolved_status: str | None = Query(default=None, alias="resolved"),
        handoff: bool | None = None,
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
            reason=reason,
            resolved_status=resolved_status,
            handoff=handoff,
        )

    @app.get("/api/admin/reconciliation/operations-summary")
    async def reconciliation_operations_summary(
        days: int = Query(default=7, ge=1, le=186),
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
        days: int = Query(default=7, ge=1, le=186),
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
        days: int = Query(default=7, ge=1, le=186),
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
        days: int = Query(default=30, ge=1, le=186),
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
        days: int = Query(default=30, ge=1, le=186),
        preset: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.knowledge.read")
        return await query_service.document_performance(
            actor,
            document_id,
            preset=preset,
            days=days,
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
        )

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
        if job.download_bytes is not None:
            content = job.download_bytes
            media_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        elif job.download_content:
            content = job.download_content
            media_type = "text/csv" if export_format == "csv" else "application/json"
        else:
            raise HTTPException(status_code=404, detail="Export content is not available.")
        filename = f"{job_id}.{export_format}"
        await query_service.export_jobs.record_download(job_id, actor=actor)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Phase 2 scaffold
    @app.get("/api/faqs")
    async def list_faqs(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return {"items": phase2.list_faqs()}

    @app.post("/api/faqs")
    async def create_faq(payload: FaqCreateRequest, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        import uuid

        record = FaqRecord(
            faq_id=str(uuid.uuid4()),
            faq_key=payload.faq_key,
            question=payload.question,
            answer=payload.answer,
            owner_unit_id=payload.owner_unit_id,
        )
        phase2.faqs.append(record)
        return {"faq": record.model_dump()}

    @app.get("/api/quality-cases")
    async def list_quality_cases(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        return {"items": phase2.list_quality_cases()}

    @app.post("/api/quality-cases")
    async def create_quality_case(
        payload: QualityCaseCreateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        import uuid

        record = QualityCaseRecord(
            case_id=str(uuid.uuid4()),
            title=payload.title,
            case_type=payload.case_type,
            owner_unit_id=payload.owner_unit_id,
        )
        phase2.quality_cases.append(record)
        return {"case": record.model_dump()}

    @app.get("/api/sync-jobs")
    async def list_sync_jobs(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.knowledge.read")
        return {"items": phase2.list_sync_jobs()}

    @app.post("/api/sync-jobs")
    async def create_sync_job(payload: SyncJobCreateRequest, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.knowledge.read")
        import uuid

        record = SyncJobRecord(
            job_id=str(uuid.uuid4()),
            scope_type=payload.scope_type,
            reason=payload.reason,
        )
        phase2.sync_jobs.append(record)
        return {"job": record.model_dump()}

    # Phase 3 scaffold
    @app.get("/api/prompts")
    async def list_prompts(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        return {"items": phase3.list_prompts()}

    @app.post("/api/prompts/candidates")
    async def create_prompt_candidate(
        payload: PromptCandidateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        import hashlib
        import uuid

        content_hash = hashlib.sha256(payload.template_summary.encode("utf-8")).hexdigest()
        record = PromptVersionRecord(
            prompt_id=payload.prompt_id,
            version=str(uuid.uuid4())[:8],
            status="CANDIDATE",
            content_hash=content_hash,
            change_reason=payload.change_reason,
        )
        phase3.prompts.append(record)
        return {"prompt": record.model_dump()}

    @app.get("/api/feature-flags")
    async def list_feature_flags(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        return {"items": phase3.list_feature_flags()}

    @app.post("/api/feature-flags/candidates")
    async def create_feature_flag(payload: FeatureFlagRecord, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.config.read")
        phase3.feature_flags.append(payload)
        return {"flag": payload.model_dump()}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
