from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import CAPABILITIES, ActorContext
from agent_service.operations.audit_errors import AuditWriteError

from .auth import BackofficeAuthError, header_auth_allowed, resolve_actor
from .budget_domain import (
    BudgetService,
    FileBudgetRepository,
    FirestoreBudgetRepository,
)
from .example_domain import (
    ExampleService,
    FileExampleRepository,
    FirestoreExampleRepository,
)
from .faq_domain import (
    FaqAuthorizationError,
    FaqContent,
    FaqDomainError,
    FaqDomainService,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
    FileFaqRepository,
    FirestoreFaqRepository,
)
from .prompt_domain import FilePromptRepository, FirestorePromptRepository, PromptPocService
from .quality_domain import (
    FileQualityRepository,
    FirestoreQualityRepository,
    QualityService,
)
from .governance_domain import (
    GovernanceService,
)
from .governance_routes import register_governance_routes
from .services.periods import PeriodPolicyError
from .services.query_audit import record_query_audit
from .services.query_service import BackofficeQueryService
from .services.rate_limit import ExportRateLimiter, RateLimitExceeded
from .services.reconciliation import (
    reconcile_costs_summary,
    reconcile_issues_summary,
    reconcile_operations_summary,
)
from .settings import BackofficeSettings
from .sync_domain import FileSyncRepository, FirestoreSyncRepository, SyncService

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
    idempotency_key: str | None = None


class FaqCreateRequest(BaseModel):
    faq_key: str
    question: str
    answer: str
    category: str
    keywords: tuple[str, ...]
    owner_unit_id: str
    business_contact: str
    issue_type_ids: tuple[str, ...]
    audience_type: Literal["ALL", "GROUPS"]
    audience_group_ids: tuple[str, ...] = ()
    effective_at: datetime | None = None
    review_due_at: datetime | None = None

    def to_content(self) -> FaqContent:
        return FaqContent.model_validate(
            self.model_dump(exclude={"expected_etag"})
        )


class FaqEditRequest(FaqCreateRequest):
    expected_etag: int = Field(ge=1)


class FaqTestCreateRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    kind: Literal["POSITIVE", "NEGATIVE"]
    utterance: str = Field(min_length=1)
    expected_audience_group_ids: tuple[str, ...] = ()
    source_type: Literal["MANUAL", "CONVERSATION"] = "MANUAL"
    source_correlation_id: str | None = None


class FaqTransitionRequest(BaseModel):
    expected_etag: int = Field(ge=1)


class FaqReviewRequest(FaqTransitionRequest):
    approve: bool
    reason: str = Field(min_length=1)


class FaqReasonRequest(FaqTransitionRequest):
    reason: str = Field(min_length=1)


class ExampleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    expected_issue_type_id: str
    expected_route: Literal["FAQ", "KNOWLEDGE", "TICKET", "HANDOFF"]
    label: Literal["POSITIVE", "NEGATIVE"]
    reason: str | None = None
    source_correlation_id: str | None = None


class ExampleUpdateRequest(ExampleCreateRequest):
    expected_etag: int = Field(ge=1)


class ExampleReviewRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    approve: bool
    reason: str = Field(min_length=1)


class ExampleRetireRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    reason: str = Field(min_length=1)


class QualityCandidateRefreshRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=186)


class QualityCandidateMergeRequest(BaseModel):
    candidate_ids: tuple[str, ...] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    assignee_id: str | None = None
    target_due_at: datetime | None = None


class QualityCaseUpdateRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    assignee_id: str | None = None
    target_due_at: datetime | None = None


class QualityCaseTransitionRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    status: Literal[
        "TRIAGED", "IN_PROGRESS", "WAITING_REVIEW", "OBSERVING",
        "RESOLVED", "WONT_FIX", "DUPLICATE",
    ]
    reason: str | None = None
    resolution_type: str | None = None


class QualityContentLinkRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    faq_id: str | None = None
    document_id: str | None = None


class QualityFaqDraftRequest(BaseModel):
    expected_case_etag: int = Field(ge=1)
    faq_key: str
    question: str
    answer: str
    category: str
    keywords: tuple[str, ...]
    business_contact: str
    audience_type: Literal["ALL", "GROUPS"]
    audience_group_ids: tuple[str, ...] = ()
    effective_at: datetime | None = None
    review_due_at: datetime | None = None


class QuestionClusterCorrectionRequest(BaseModel):
    cluster_ids: tuple[str, ...] = Field(min_length=1)
    action: Literal["RENAME", "ACCEPT", "REJECT", "MERGE", "SPLIT"]
    name: str | None = None
    candidate_groups: tuple[tuple[str, ...], ...] = ()


class SyncJobCreateRequest(BaseModel):
    scope_type: Literal["ALL", "FAQ", "DOCUMENT", "FAILED"]
    scope_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=3)


class SyncJobActionRequest(BaseModel):
    reason: str = Field(min_length=3)
    expected_etag: int | None = Field(default=None, ge=1)


class BudgetPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["PERSONAL", "SERVICE", "TEAM", "TENANT", "GLOBAL"]
    scope_id: str = Field(min_length=1)
    period: Literal["DAILY", "MONTHLY"]
    measure: Literal["TWD", "USD", "TOKEN", "LLM_CALL_COUNT"]
    warning_threshold: float = Field(gt=0)
    critical_threshold: float = Field(gt=0)
    owner_unit_id: str = Field(min_length=1)
    notification_target_ids: tuple[str, ...]


class BudgetPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_etag: int = Field(ge=1)
    warning_threshold: float = Field(gt=0)
    critical_threshold: float = Field(gt=0)
    notification_target_ids: tuple[str, ...]


class BudgetPolicyStateRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    enabled: bool
    reason: str = Field(min_length=3)


class PromptCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_prompt_version: str
    dataset_version: str
    taxonomy_version: str
    data_range_start: datetime
    data_range_end: datetime
    masking_policy_version: str


def create_app(
    settings: BackofficeSettings | None = None,
    *,
    eval_flow_harness: object | None = None,
) -> FastAPI:
    resolved_settings = settings or BackofficeSettings.from_env()
    query_service = BackofficeQueryService(resolved_settings)
    export_rate_limiter = ExportRateLimiter()

    class ActiveFaqTaxonomy:
        def require_active(self, issue_type_id: str) -> None:
            issue_type = query_service.taxonomy.get(issue_type_id)
            if issue_type is None or issue_type.status != "ACTIVE":
                raise FaqValidationError(f"inactive issue type: {issue_type_id}")

    faq_store_mode = resolved_settings.faq_store_mode.upper()
    if faq_store_mode == "FILE":
        faq_store_path = resolved_settings.faq_store_path or (
            resolved_settings.ops_store_path.parent / "phase2" / "faqs.json"
        )
        faq_repository = FileFaqRepository(faq_store_path)
    elif faq_store_mode == "FIRESTORE":
        from google.cloud import firestore

        faq_repository = FirestoreFaqRepository(
            firestore.Client(project=resolved_settings.gcp_project_id),
            collection_prefix=resolved_settings.faq_firestore_collection_prefix,
        )
    else:
        raise ValueError(f"Unsupported FAQ store mode: {faq_store_mode}")
    faq_service = FaqDomainService(faq_repository, taxonomy=ActiveFaqTaxonomy())

    example_store_mode = resolved_settings.example_store_mode.upper()
    if example_store_mode == "FILE":
        example_store_path = resolved_settings.example_store_path or (
            resolved_settings.ops_store_path.parent / "phase2" / "examples.json"
        )
        example_repository = FileExampleRepository(example_store_path)
    elif example_store_mode == "FIRESTORE":
        from google.cloud import firestore

        example_repository = FirestoreExampleRepository(
            firestore.Client(project=resolved_settings.gcp_project_id),
            collection_prefix=resolved_settings.example_firestore_collection_prefix,
        )
    else:
        raise ValueError(f"Unsupported example store mode: {example_store_mode}")
    example_service = ExampleService(example_repository, taxonomy=ActiveFaqTaxonomy())

    quality_store_mode = resolved_settings.quality_store_mode.upper()
    if quality_store_mode == "FILE":
        quality_store_path = resolved_settings.quality_store_path or (
            resolved_settings.ops_store_path.parent / "phase2" / "quality.json"
        )
        quality_repository = FileQualityRepository(quality_store_path)
    elif quality_store_mode == "FIRESTORE":
        from google.cloud import firestore

        quality_repository = FirestoreQualityRepository(
            firestore.Client(project=resolved_settings.gcp_project_id),
            collection=resolved_settings.quality_firestore_collection,
        )
    else:
        raise ValueError(f"Unsupported quality store mode: {quality_store_mode}")
    quality_service = QualityService(quality_repository)

    sync_store_mode = resolved_settings.sync_store_mode.upper()
    if sync_store_mode == "FILE":
        sync_store_path = resolved_settings.sync_store_path or (
            resolved_settings.ops_store_path.parent / "phase2" / "sync_jobs.json"
        )
        sync_repository = FileSyncRepository(sync_store_path)
    elif sync_store_mode == "FIRESTORE":
        from google.cloud import firestore

        sync_repository = FirestoreSyncRepository(
            firestore.Client(project=resolved_settings.gcp_project_id),
            collection=resolved_settings.sync_firestore_collection,
        )
    else:
        raise ValueError(f"Unsupported sync store mode: {sync_store_mode}")
    sync_service = SyncService(sync_repository)
    configured_targets: dict[str, str] = {}
    valid_notification_channels = {"TEAMS", "EMAIL", "NOTIFICATION_CENTER"}
    for entry in resolved_settings.budget_notification_targets:
        target_id, separator, channel = entry.partition("=")
        normalized_channel = channel.strip().upper()
        if not separator or not target_id.strip() or normalized_channel not in valid_notification_channels:
            raise ValueError(f"Invalid budget notification target configuration: {entry}")
        configured_targets[target_id.strip()] = normalized_channel
    budget_store_mode = resolved_settings.budget_store_mode.upper()
    if budget_store_mode == "FILE":
        budget_store_path = resolved_settings.budget_store_path or (
            resolved_settings.ops_store_path.parent / "phase2" / "budgets.json"
        )
        budget_repository = FileBudgetRepository(budget_store_path)
    elif budget_store_mode == "FIRESTORE":
        from google.cloud import firestore

        budget_repository = FirestoreBudgetRepository(
            firestore.Client(project=resolved_settings.gcp_project_id),
            collection=resolved_settings.budget_firestore_collection,
        )
    else:
        raise ValueError(f"Unsupported budget store mode: {budget_store_mode}")
    budget_service = BudgetService(
        budget_repository,
        notification_targets=configured_targets,
    )
    prompt_store_mode = resolved_settings.prompt_poc_store_mode.upper()
    if prompt_store_mode == "FILE":
        prompt_store_path = resolved_settings.prompt_poc_store_path or (
            resolved_settings.ops_store_path.parent / "phase2" / "prompt_candidates.json"
        )
        prompt_repository = FilePromptRepository(prompt_store_path)
    elif prompt_store_mode == "FIRESTORE":
        from google.cloud import firestore

        prompt_repository = FirestorePromptRepository(
            firestore.Client(project=resolved_settings.gcp_project_id),
            collection=resolved_settings.prompt_poc_firestore_collection,
        )
    else:
        raise ValueError(f"Unsupported Prompt POC store mode: {prompt_store_mode}")
    prompt_effective_at = (
        datetime.fromisoformat(resolved_settings.prompt_active_effective_at.replace("Z", "+00:00"))
        if resolved_settings.prompt_active_effective_at
        else None
    )
    if prompt_effective_at is not None and prompt_effective_at.utcoffset() is None:
        raise ValueError("AI_OPS_PROMPT_ACTIVE_EFFECTIVE_AT requires a timezone")
    prompt_service = PromptPocService(
        prompt_repository,
        active_effective_at=prompt_effective_at,
    )
    governance_store_mode = resolved_settings.governance_store_mode.upper()
    from ai_ops_backoffice.governance_domain.store_factory import build_governance_repository

    governance_store_path = resolved_settings.governance_store_path or (
        resolved_settings.ops_store_path.parent / "phase3" / "governance.json"
    )
    governance_repository = build_governance_repository(
        store_mode=governance_store_mode,
        file_path=governance_store_path,
        firestore_project=resolved_settings.gcp_project_id,
        firestore_collection=resolved_settings.governance_firestore_collection,
    )
    governance_service = GovernanceService(
        governance_repository,
        eval_flow_harness=eval_flow_harness,  # type: ignore[arg-type]
    )
    from agent_service.operations.policy_runtime import (
        PolicyRuntime,
        configure_policy_runtime,
        get_policy_runtime,
    )

    existing_runtime = get_policy_runtime()
    policy_settings = (
        existing_runtime._settings
        if existing_runtime is not None
        else query_service._runtime.settings
    )
    configure_policy_runtime(
        PolicyRuntime(settings=policy_settings, governance=governance_service)
    )
    sync_worker = ActorContext(
        user_id="ai-ops-sync-worker",
        display_name="AI Ops Sync Worker",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(),
    )

    async def run_sync_job(job_id: str) -> None:
        try:
            validating = sync_service.set_stage(job_id, status="VALIDATING", actor=sync_worker)
            job = validating["job"]
            adapter_url = resolved_settings.sync_adapter_url
            if not adapter_url:
                sync_service.set_stage(
                    job_id,
                    status="FAILED",
                    actor=sync_worker,
                    error_summary="SYNC_ADAPTER_UNAVAILABLE",
                )
                return
            sync_service.set_stage(job_id, status="BUILDING", actor=sync_worker)
            headers = {}
            if resolved_settings.service_token:
                headers["Authorization"] = f"Bearer {resolved_settings.service_token}"
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{adapter_url.rstrip('/')}/api/sync",
                    headers=headers,
                    json={
                        "scopeType": job["scope_type"],
                        "scopeIds": job["scope_ids"],
                        "correlationId": job["correlation_id"],
                        "resumeCheckpoint": job["retry_checkpoint_stage"],
                    },
                )
            if response.status_code >= 400:
                sync_service.set_stage(
                    job_id,
                    status="FAILED",
                    actor=sync_worker,
                    error_summary=f"Adapter returned HTTP {response.status_code}",
                )
                return
            result = response.json()
            if not result.get("targetRelease") or not result.get("indexSettingVersion"):
                sync_service.set_stage(
                    job_id,
                    status="FAILED",
                    actor=sync_worker,
                    error_summary="SYNC_RELEASE_EVIDENCE_MISSING",
                )
                return
            sync_service.set_stage(
                job_id,
                status="VERIFYING",
                actor=sync_worker,
                document_count=int(result.get("documentCount") or 0),
                warnings=tuple(result.get("warnings") or ()),
            )
            sync_service.set_stage(
                job_id,
                status="COMPLETED",
                actor=sync_worker,
                document_count=int(result.get("documentCount") or 0),
                warnings=tuple(result.get("warnings") or ()),
                target_release=result.get("targetRelease"),
                index_setting_version=result.get("indexSettingVersion"),
                artifact_uri=result.get("artifactUri"),
            )
        except Exception as error:
            logger.exception("Sync job %s failed", job_id)
            with suppress(FaqDomainError):
                sync_service.set_stage(
                    job_id,
                    status="FAILED",
                    actor=sync_worker,
                    error_summary=type(error).__name__,
                )

    async def quality_metrics_by_issue(actor: ActorContext) -> dict[str, dict[str, float]]:
        summary = await query_service.issues_summary(actor, days=30)
        return {
            str(item["issueTypeId"]): {
                "count": float(item["count"]),
                "noAnswerRate": float(item["noAnswerRate"]),
                "negativeFeedbackRate": float(item["negativeFeedbackRate"]),
                "handoffRate": float(item["handoffRate"]),
                "estimatedCostUsd": float(item["estimatedCostUsd"]),
            }
            for item in summary["items"]
        }

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
        x_backoffice_tenant_id: str | None = Header(default=None, alias="X-Backoffice-Tenant-Id"),
    ):
        try:
            return resolve_actor(
                auth_mode=resolved_settings.auth_mode,
                authorization=authorization,
                header_user_id=x_backoffice_user_id,
                header_user_name=x_backoffice_user_name,
                header_role=x_backoffice_role,
                header_owner_units=x_backoffice_owner_units,
                header_tenant_id=x_backoffice_tenant_id,
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
        stop_sweeper = asyncio.Event()
        query_service.export_jobs.configure_execution_backend(query_service)
        try:
            recovered = await query_service.export_jobs.recover_interrupted_jobs()
            if recovered:
                logger.info("Recovered %s interrupted export jobs", recovered)
        except Exception:
            logger.exception("Failed to recover interrupted export jobs.")

        async def sweep_expired_exports() -> None:
            while not stop_sweeper.is_set():
                try:
                    await query_service.export_jobs.purge_expired_jobs()
                except Exception:
                    logger.exception("Failed to purge expired export jobs.")
                try:
                    await asyncio.wait_for(stop_sweeper.wait(), timeout=60)
                except TimeoutError:
                    continue

        sweeper = asyncio.create_task(sweep_expired_exports())
        recovery = asyncio.create_task(
            query_service.export_jobs.run_recovery_scanner(stop_sweeper)
        )
        try:
            yield
        finally:
            stop_sweeper.set()
            for task in (sweeper, recovery):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

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

    @app.exception_handler(FaqAuthorizationError)
    async def faq_authorization_handler(_request, exc: FaqAuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(FaqNotFoundError)
    async def faq_not_found_handler(_request, exc: FaqNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(FaqVersionConflictError)
    @app.exception_handler(FaqIdempotencyConflictError)
    @app.exception_handler(FaqTransitionError)
    async def faq_conflict_handler(_request, exc: FaqDomainError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(FaqValidationError)
    async def faq_validation_handler(_request, exc: FaqValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

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
            "ownerUnitIds": list(actor.owner_unit_ids),
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

    # Phase 2 FAQ governance
    @app.get("/api/faqs")
    async def list_faqs(
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        items = faq_service.list_faqs(actor=actor)
        if status:
            items = [item for item in items if item["faq"]["status"] == status]
        if owner_unit_id:
            items = [
                item for item in items
                if item["version"]["content"]["owner_unit_id"] == owner_unit_id
            ]
        if query:
            needle = query.casefold()
            items = [
                item for item in items
                if any(
                    needle in value.casefold()
                    for value in (
                        item["faq"]["faq_key"],
                        item["version"]["content"]["question"],
                    )
                )
            ]
        return {"items": items, "total": len(items)}

    @app.get("/api/faqs/{faq_id}")
    async def get_faq(faq_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        return faq_service.detail(faq_id=faq_id, actor=actor)

    @app.get("/api/faqs/{faq_id}/performance")
    async def get_faq_performance(
        faq_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        detail = faq_service.detail(faq_id=faq_id, actor=actor)
        faq_key = detail["faq"]["faq_key"]
        return await query_service.faq_performance(actor, faq_key=faq_key)

    @app.post("/api/faqs")
    async def create_faq(
        payload: FaqCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return faq_service.create(
            content=payload.to_content(),
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.put("/api/faqs/{faq_id}")
    async def edit_faq(
        faq_id: str,
        payload: FaqEditRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return faq_service.edit(
            faq_id=faq_id,
            content=payload.to_content(),
            actor=actor,
            expected_etag=payload.expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/tests")
    async def add_faq_test(
        faq_id: str,
        version_id: str,
        payload: FaqTestCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return faq_service.add_test(
            faq_id=faq_id,
            version_id=version_id,
            kind=payload.kind,
            utterance=payload.utterance,
            expected_audience_group_ids=payload.expected_audience_group_ids,
            source_type=payload.source_type,
            source_correlation_id=payload.source_correlation_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/submit")
    async def submit_faq(
        faq_id: str,
        version_id: str,
        payload: FaqTransitionRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.write")
        return faq_service.submit(
            faq_id=faq_id,
            version_id=version_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/review")
    async def review_faq(
        faq_id: str,
        version_id: str,
        payload: FaqReviewRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.review")
        return faq_service.review(
            faq_id=faq_id,
            version_id=version_id,
            approve=payload.approve,
            reason=payload.reason,
            actor=actor,
            expected_etag=payload.expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/activate")
    async def activate_faq(
        faq_id: str,
        version_id: str,
        payload: FaqReasonRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.activate")
        result = faq_service.activate(
            faq_id=faq_id,
            version_id=version_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        observing = quality_service.observe_faq(
            faq_id,
            baseline_by_issue=await quality_metrics_by_issue(actor),
            actor=actor,
        )
        return {**result, "observingCases": observing["items"]}

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/rollback")
    async def rollback_faq(
        faq_id: str,
        version_id: str,
        payload: FaqReasonRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.activate")
        result = faq_service.rollback(
            faq_id=faq_id,
            version_id=version_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        observing = quality_service.observe_faq(
            faq_id,
            baseline_by_issue=await quality_metrics_by_issue(actor),
            actor=actor,
        )
        return {**result, "observingCases": observing["items"]}

    @app.post("/api/faqs/{faq_id}/disable")
    async def disable_faq(
        faq_id: str,
        payload: FaqReasonRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.disable")
        return faq_service.disable(
            faq_id=faq_id,
            actor=actor,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    # Phase 2 governed quality examples
    @app.get("/api/examples")
    async def list_examples(
        source_type: Literal["FAQ", "DOCUMENT", "CONVERSATION", "MANUAL"] | None = None,
        source_id: str | None = None,
        status: Literal["DRAFT", "VERIFIED", "REJECTED", "RETIRED"] | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.read")
        items = example_service.list_examples(
            actor=actor,
            source_type=source_type,
            source_id=source_id,
            status=status,
        )
        return {"items": items, "total": len(items)}

    @app.get("/api/examples/{example_id}")
    async def get_example(example_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.examples.read")
        return example_service.detail(example_id, actor=actor)

    @app.post("/api/faqs/{faq_id}/versions/{version_id}/examples")
    async def create_faq_example(
        faq_id: str,
        version_id: str,
        payload: ExampleCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        faq = faq_service.detail(faq_id=faq_id, actor=actor)
        source_version = next(
            (item for item in faq["versions"] if item["version_id"] == version_id),
            None,
        )
        if source_version is None:
            raise FaqNotFoundError(version_id)
        return example_service.create(
            source_type="FAQ",
            source_id=faq_id,
            source_version_id=version_id,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=source_version["content"]["owner_unit_id"],
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/examples/manual")
    async def create_manual_example(
        payload: ExampleCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        return example_service.create(
            source_type="MANUAL",
            source_id=f"manual:{actor.user_id}",
            source_version_id=None,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=resolved_settings.default_owner_unit_id,
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/knowledge/{document_id}/versions/{version_id}/examples")
    async def create_document_example(
        document_id: str,
        version_id: str,
        payload: ExampleCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        inventory = await query_service.list_documents(
            actor,
            query=document_id,
            limit=100,
        )
        if inventory.get("portalStatus") != "available":
            raise HTTPException(status_code=503, detail="Knowledge inventory is unavailable.")
        source_document = next(
            (item for item in inventory["items"] if item.get("documentId") == document_id),
            None,
        )
        if source_document is None:
            raise FaqNotFoundError(document_id)
        valid_versions = {
            source_document.get("currentPublishedVersionId"),
            source_document.get("draftVersionId"),
        }
        if version_id not in valid_versions:
            raise FaqNotFoundError(version_id)
        owner_unit_id = source_document.get("ownerUnitId")
        if not owner_unit_id:
            raise FaqValidationError("document owner unit is unavailable")
        return example_service.create(
            source_type="DOCUMENT",
            source_id=document_id,
            source_version_id=version_id,
            source_correlation_id=payload.source_correlation_id,
            owner_unit_id=owner_unit_id,
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/conversations/{conversation_id}/examples")
    async def create_conversation_example(
        conversation_id: str,
        payload: ExampleCreateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        source_conversation = await query_service.conversation_detail(actor, conversation_id)
        if source_conversation is None:
            raise FaqNotFoundError(conversation_id)
        owner_unit_id = source_conversation.get("ownerUnitId")
        if not owner_unit_id:
            raise FaqValidationError("conversation owner unit is unavailable or ambiguous")
        turns = source_conversation.get("turns") or []
        source_correlation_id = turns[-1].get("correlationId") if turns else None
        return example_service.create(
            source_type="CONVERSATION",
            source_id=conversation_id,
            source_version_id=None,
            source_correlation_id=source_correlation_id,
            owner_unit_id=owner_unit_id,
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.put("/api/examples/{example_id}")
    async def update_example(
        example_id: str,
        payload: ExampleUpdateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.write")
        return example_service.update(
            example_id,
            text=payload.text,
            expected_issue_type_id=payload.expected_issue_type_id,
            expected_route=payload.expected_route,
            label=payload.label,
            reason=payload.reason,
            expected_etag=payload.expected_etag,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/examples/{example_id}/review")
    async def review_example(
        example_id: str,
        payload: ExampleReviewRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.verify")
        return example_service.review(
            example_id,
            approve=payload.approve,
            reason=payload.reason,
            expected_etag=payload.expected_etag,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/examples/{example_id}/retire")
    async def retire_example(
        example_id: str,
        payload: ExampleRetireRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.retire")
        return example_service.retire(
            example_id,
            reason=payload.reason,
            expected_etag=payload.expected_etag,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.get("/api/quality-cases")
    async def list_quality_cases(
        status: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = quality_service.list_cases(actor=actor, status=status)
        return {"items": items, "total": len(items)}

    @app.get("/api/quality-cases/{case_id}")
    async def get_quality_case(case_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        return quality_service.case_detail(case_id, actor=actor)

    @app.put("/api/quality-cases/{case_id}")
    async def update_quality_case(
        case_id: str,
        payload: QualityCaseUpdateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.update_case(
            case_id,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            assignee_id=payload.assignee_id,
            target_due_at=payload.target_due_at,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.post("/api/quality-cases/{case_id}/transition")
    async def transition_quality_case(
        case_id: str,
        payload: QualityCaseTransitionRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        capability = (
            "ops.quality.resolve"
            if payload.status in {"RESOLVED", "WONT_FIX", "DUPLICATE"}
            else "ops.quality.write"
        )
        require_capability(actor, capability)
        return quality_service.transition_case(
            case_id,
            status=payload.status,
            reason=payload.reason,
            resolution_type=payload.resolution_type,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.post("/api/quality-cases/{case_id}/content")
    async def link_quality_case_content(
        case_id: str,
        payload: QualityContentLinkRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        if payload.faq_id:
            faq = faq_service.detail(faq_id=payload.faq_id, actor=actor)
            if faq["versions"][-1]["content"]["owner_unit_id"] != case["owner_unit_id"]:
                raise FaqValidationError("linked FAQ must belong to the Quality Case owner unit")
        if payload.document_id:
            inventory = await query_service.list_documents(
                actor,
                query=payload.document_id,
                limit=100,
            )
            document = next(
                (
                    item for item in inventory.get("items", [])
                    if item.get("documentId") == payload.document_id
                ),
                None,
            )
            if document is None:
                raise FaqNotFoundError(payload.document_id)
            if document.get("ownerUnitId") != case["owner_unit_id"]:
                raise FaqValidationError("linked document must belong to the Quality Case owner unit")
        return quality_service.link_content(
            case_id,
            faq_id=payload.faq_id,
            document_id=payload.document_id,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.post("/api/quality-cases/{case_id}/faq-draft")
    async def create_quality_case_faq_draft(
        case_id: str,
        payload: QualityFaqDraftRequest,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        require_capability(actor, "ops.faq.write")
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        if not case["issue_type_id"]:
            raise FaqValidationError("Quality Case requires an issue type before creating a FAQ")
        content = FaqContent(
            faq_key=payload.faq_key,
            question=payload.question,
            answer=payload.answer,
            category=payload.category,
            keywords=payload.keywords,
            owner_unit_id=case["owner_unit_id"],
            business_contact=payload.business_contact,
            issue_type_ids=(case["issue_type_id"],),
            audience_type=payload.audience_type,
            audience_group_ids=payload.audience_group_ids,
            effective_at=payload.effective_at,
            review_due_at=payload.review_due_at,
        )
        faq_result = faq_service.create(
            content=content,
            actor=actor,
            correlation_id=correlation_id,
        )
        linked = quality_service.link_content(
            case_id,
            faq_id=faq_result["faq"]["faq_id"],
            document_id=None,
            expected_etag=payload.expected_case_etag,
            actor=actor,
        )
        return {**faq_result, "case": linked["case"]}

    @app.post("/api/quality-cases/{case_id}/observation/refresh")
    async def refresh_quality_case_observation(
        case_id: str,
        payload: FaqTransitionRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        case = quality_service.case_detail(case_id, actor=actor)["case"]
        metrics = (await quality_metrics_by_issue(actor)).get(case["issue_type_id"] or "", {})
        return quality_service.record_observation(
            case_id,
            metrics=metrics,
            expected_etag=payload.expected_etag,
            actor=actor,
        )

    @app.get("/api/quality-candidates")
    async def list_quality_candidates(
        status: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = quality_service.list_candidates(actor=actor, status=status)
        return {"items": items, "total": len(items)}

    @app.post("/api/quality-candidates/refresh")
    async def refresh_quality_candidates(
        payload: QualityCandidateRefreshRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        seeds = await query_service.quality_candidate_seeds(actor, days=payload.days)
        for seed in seeds:
            quality_service.add_candidate(**seed, actor=actor)
        items = quality_service.list_candidates(actor=actor, status="OPEN")
        return {"items": items, "total": len(items), "scanned": len(seeds)}

    @app.post("/api/quality-candidates/merge")
    async def merge_quality_candidates(
        payload: QualityCandidateMergeRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.merge_candidates(
            payload.candidate_ids,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            assignee_id=payload.assignee_id,
            target_due_at=payload.target_due_at,
            actor=actor,
        )

    @app.get("/api/gaps/summary")
    async def gap_summary(
        days: int = Query(default=30, ge=1, le=186),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        issues = await query_service.issues_summary(actor, days=days)
        weights = {
            "frequency": 30.0,
            "noAnswerRate": 20.0,
            "negativeFeedbackRate": 25.0,
            "handoffRate": 15.0,
            "estimatedCostUsd": 10.0,
        }
        items = []
        max_frequency = max((item["count"] for item in issues["items"]), default=1)
        max_cost = max((item["estimatedCostUsd"] for item in issues["items"]), default=1) or 1
        for issue in issues["items"]:
            components = {
                "frequency": round(issue["count"] / max_frequency * weights["frequency"], 4),
                "noAnswerRate": round(issue["noAnswerRate"] * weights["noAnswerRate"], 4),
                "negativeFeedbackRate": round(
                    issue["negativeFeedbackRate"] * weights["negativeFeedbackRate"], 4
                ),
                "handoffRate": round(issue["handoffRate"] * weights["handoffRate"], 4),
                "estimatedCostUsd": round(
                    issue["estimatedCostUsd"] / max_cost * weights["estimatedCostUsd"], 4
                ),
            }
            items.append({**issue, "gapScore": round(sum(components.values()), 4), "components": components})
        items.sort(key=lambda item: item["gapScore"], reverse=True)
        return {
            "scoreVersion": "gap-score-v1",
            "weights": weights,
            "taxonomyVersion": issues["taxonomyVersion"],
            "items": items,
        }

    @app.get("/api/question-clusters")
    async def list_question_clusters(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        items = quality_service.list_clusters(actor=actor)
        return {"items": items, "total": len(items)}

    @app.post("/api/question-clusters/generate")
    async def generate_question_clusters(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.generate_clusters(actor=actor)

    @app.post("/api/question-clusters/correct")
    async def correct_question_clusters(
        payload: QuestionClusterCorrectionRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.write")
        return quality_service.correct_clusters(
            payload.cluster_ids,
            action=payload.action,
            name=payload.name,
            candidate_groups=payload.candidate_groups,
            actor=actor,
        )

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

    @app.get("/api/budget-policies")
    async def list_budget_policies(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.budget.read")
        items = budget_service.list_policies(actor=actor)
        return {
            "items": items,
            "total": len(items),
            "notificationTargets": sorted(configured_targets),
        }

    @app.get("/api/budget-policies/{policy_id}")
    async def get_budget_policy(
        policy_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.read")
        return {"policy": budget_service.policy_detail(policy_id, actor=actor)}

    @app.post("/api/budget-policies")
    async def create_budget_policy(
        payload: BudgetPolicyCreateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.write")
        definitions = query_service.metrics_definitions()
        return budget_service.create_policy(
            **payload.model_dump(),
            pricing_version=str(definitions["pricingVersion"]),
            exchange_rate_version=str(definitions["metricsDefinitionVersion"]),
            actor=actor,
        )

    @app.put("/api/budget-policies/{policy_id}")
    async def update_budget_policy(
        policy_id: str,
        payload: BudgetPolicyUpdateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.write")
        return budget_service.update_policy(policy_id, **payload.model_dump(), actor=actor)

    @app.post("/api/budget-policies/{policy_id}/state")
    async def set_budget_policy_state(
        policy_id: str,
        payload: BudgetPolicyStateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.write")
        return budget_service.set_policy_enabled(
            policy_id,
            enabled=payload.enabled,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            actor=actor,
        )

    @app.post("/api/budget-policies/{policy_id}/evaluate")
    async def evaluate_budget_policy(
        policy_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.evaluate")
        policy = budget_service.policy_detail(policy_id, actor=actor)
        usage = await query_service.budget_usage(
            actor,
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            period_type=str(policy["period"]),
            measure=str(policy["measure"]),
        )
        result = budget_service.evaluate(
            policy_id,
            period_key=str(usage["periodKey"]),
            actual_value=float(usage["actualValue"]),
            coverage=float(usage["coverage"]),
            pricing_version=str(usage["pricingVersion"]),
            exchange_rate_version=str(usage["exchangeRateVersion"]),
            actor=actor,
        )
        return {**result, "usage": usage}

    @app.get("/api/alerts")
    async def list_alerts(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.alerts.read")
        items = budget_service.list_alerts(actor=actor)
        return {"items": items, "total": len(items)}

    @app.get("/api/alerts/{alert_id}")
    async def get_alert(alert_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.alerts.read")
        return {"alert": budget_service.alert_detail(alert_id, actor=actor)}

    @app.post("/api/alerts/{alert_id}/acknowledge")
    async def acknowledge_alert(
        alert_id: str,
        payload: FaqReasonRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.alerts.manage")
        return budget_service.change_alert(
            alert_id,
            action="ACKNOWLEDGE",
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            actor=actor,
        )

    @app.post("/api/alerts/{alert_id}/deliveries/{delivery_id}/retry")
    async def retry_alert_delivery(
        alert_id: str,
        delivery_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.alerts.manage")
        alert = budget_service.alert_detail(alert_id, actor=actor)
        if delivery_id not in {item["delivery_id"] for item in alert["deliveries"]}:
            raise FaqNotFoundError(delivery_id)
        return budget_service.retry_delivery(delivery_id, actor=actor)

    @app.post("/api/alerts/{alert_id}/resolve")
    async def resolve_alert(
        alert_id: str,
        payload: FaqReasonRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.alerts.manage")
        return budget_service.change_alert(
            alert_id,
            action="RESOLVE",
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            actor=actor,
        )

    @app.get("/api/prompts/active")
    async def get_active_prompt(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return {"prompt": prompt_service.active(actor=actor)}

    @app.get("/api/prompts/candidates")
    async def list_prompt_candidates(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        items = prompt_service.list_candidates(actor=actor)
        return {"items": items, "total": len(items)}

    @app.get("/api/prompts/candidates/{candidate_id}")
    async def get_prompt_candidate(
        candidate_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return {"candidate": prompt_service.detail(candidate_id, actor=actor)}

    @app.get("/api/prompts/candidates/{candidate_id}/compare")
    async def compare_prompt_candidate(
        candidate_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return prompt_service.compare(candidate_id, actor=actor)

    @app.post("/api/prompts/candidates")
    async def create_prompt_candidate(
        payload: PromptCandidateRequest,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.candidates.create")
        if payload.taxonomy_version != query_service.taxonomy.version:
            raise FaqValidationError("taxonomy version is stale")
        if payload.masking_policy_version != resolved_settings.prompt_masking_policy_version:
            raise FaqValidationError("masking policy version is stale")
        verified_examples = example_service.list_examples(actor=actor, status="VERIFIED")
        return prompt_service.generate(
            **payload.model_dump(),
            verified_examples=verified_examples,
            correlation_id=correlation_id,
            actor=actor,
        )

    register_governance_routes(
        app,
        governance=governance_service,
        current_actor=current_actor,
        require_capability=require_capability,
        example_service=example_service,
        faq_service=faq_service,
        query_service=query_service,
        quality_service=quality_service,
    )

    # Phase 3 feature-flag list remains available under the governed API.
    @app.get("/api/feature-flags")
    async def list_feature_flags(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.flags.read")
        return {"items": governance_service.list_flags(actor=actor)}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
