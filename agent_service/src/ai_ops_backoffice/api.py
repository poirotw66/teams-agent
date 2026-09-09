from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from agent_service.operations.audit_errors import AuditWriteError

from .budget_domain import (
    BudgetService,
    FileBudgetRepository,
    FirestoreBudgetRepository,
)
from .notification_dispatcher import NotificationDispatcher
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
from .governance_domain import (
    GovernanceService,
)
from .governance_routes import register_governance_routes
from .deps import build_dependencies
from .routers import (
    register_budget_routes,
    register_example_routes,
    register_faq_routes,
    register_ops_read_routes,
    register_quality_routes,
    register_prompt_poc_routes,
    register_sync_routes,
)
from .knowledge_bridge import KnowledgePortalClient, build_knowledge_router
from .knowledge_bridge.errors import KnowledgeBridgeError
from .prompt_domain import FilePromptRepository, FirestorePromptRepository, PromptPocService
from .quality_domain import (
    FileQualityRepository,
    FirestoreQualityRepository,
    QualityService,
)
from .services.periods import PeriodPolicyError
from .services.query_service import BackofficeQueryService
from .services.rate_limit import ExportRateLimiter, RateLimitExceeded
from .settings import BackofficeSettings
from .workers import install_background_runtime
from .sync_domain import FileSyncRepository, FirestoreSyncRepository, SyncService

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
UI_ASSET_VERSION = "ops-ui-20260908g"


def _js_import_map_script(version: str) -> str:
    """Remap bare module URLs so nested ES imports share one cache-busted URL."""
    js_root = STATIC_DIR / "js"
    imports = {
        f"/static/js/{path.relative_to(js_root).as_posix()}": (
            f"/static/js/{path.relative_to(js_root).as_posix()}?v={version}"
        )
        for path in sorted(js_root.rglob("*.js"))
    }
    payload = json.dumps({"imports": imports}, ensure_ascii=True, indent=2)
    return f'<script type="importmap">\n{payload}\n</script>'


def _render_index_html(version: str = UI_ASSET_VERSION) -> str:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__UI_ASSET_VERSION__", version)
    marker = "<!-- AI_OPS_IMPORT_MAP -->"
    import_map = _js_import_map_script(version)
    if marker in html:
        return html.replace(marker, import_map, 1)
    return html.replace("</head>", f"    {import_map}\n  </head>", 1)


class _NoStoreStaticCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/") or path.startswith("/knowledge-ui"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def create_app(
    settings: BackofficeSettings | None = None,
    *,
    eval_flow_harness: object | None = None,
    knowledge_transport: httpx.AsyncBaseTransport | None = None,
    notification_transport: httpx.AsyncBaseTransport | None = None,
    sync_transport: httpx.AsyncBaseTransport | None = None,
    email_sender: Callable[[str, str, str], None] | None = None,
) -> FastAPI:
    resolved_settings = settings or BackofficeSettings.from_env()
    prod_issues = resolved_settings.validate_for_production()
    if prod_issues:
        raise ValueError(f"Invalid production configuration: {'; '.join(prod_issues)}")
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
    faq_service = FaqDomainService(
        faq_repository,
        taxonomy=ActiveFaqTaxonomy(),
        artifact_dir=resolved_settings.faq_artifact_dir,
    )

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
    knowledge_client = KnowledgePortalClient(
        base_url=resolved_settings.knowledge_internal_url
        or resolved_settings.knowledge_portal_url,
        service_token=resolved_settings.knowledge_service_token,
        delegation_secret=resolved_settings.knowledge_delegation_secret,
        transport=knowledge_transport,
    )

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
    notification_dispatcher = NotificationDispatcher(
        resolved_settings,
        budget_service,
        http_transport=notification_transport,
        email_sender=email_sender,
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
    from ai_ops_backoffice.governance_domain.eval_runtime import (
        resolve_backoffice_eval_harness,
    )

    resolved_eval_harness, eval_harness_status = resolve_backoffice_eval_harness(
        eval_flow_harness  # type: ignore[arg-type]
    )
    governance_service = GovernanceService(
        governance_repository,
        eval_flow_harness=resolved_eval_harness,
    )
    from ai_ops_backoffice.services.export_auth_store import FileBackedExportAuthorizationResolver
    from ai_ops_backoffice.services.export_authorization import GovernanceRevocationAuthority

    export_authority = GovernanceRevocationAuthority(
        lambda: set(governance_repository.load().revoked_principals)
    )
    query_service.export_jobs.configure_authorization_resolver(
        FileBackedExportAuthorizationResolver(
            query_service.export_jobs._store_path / "export_auth_registry.json",
            authority=export_authority,
        )
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
    (
        sync_worker,
        run_sync_job,
        check_api_health_alerts,
        evaluate_all_budgets,
        lifespan,
    ) = install_background_runtime(
        resolved_settings=resolved_settings,
        query_service=query_service,
        sync_service=sync_service,
        budget_service=budget_service,
        notification_dispatcher=notification_dispatcher,
        knowledge_transport=knowledge_transport,
        sync_transport=sync_transport,
        example_service=example_service,
        quality_service=quality_service,
        governance_service=governance_service,
    )

    deps = build_dependencies(
        resolved_settings=resolved_settings,
        query_service=query_service,
    )
    current_actor = deps.current_actor
    require_capability = deps.require_capability
    audit_read = deps.audit_read
    quality_metrics_by_issue = deps.quality_metrics_by_issue
    enrich_quality_issue_display = deps.enrich_quality_issue_display

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

    @app.exception_handler(KnowledgeBridgeError)
    async def knowledge_bridge_error_handler(_request, exc: KnowledgeBridgeError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.as_response())

    register_ops_read_routes(
        app,
        resolved_settings=resolved_settings,
        query_service=query_service,
        governance_service=governance_service,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
        export_rate_limiter=export_rate_limiter,
        example_service=example_service,
        quality_service=quality_service,
        sync_service=sync_service,
        budget_service=budget_service,
    )

    register_faq_routes(
        app,
        resolved_settings=resolved_settings,
        query_service=query_service,
        faq_service=faq_service,
        quality_service=quality_service,
        quality_metrics_by_issue=quality_metrics_by_issue,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
    )

    register_example_routes(
        app,
        resolved_settings=resolved_settings,
        query_service=query_service,
        example_service=example_service,
        faq_service=faq_service,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_quality_routes(
        app,
        resolved_settings=resolved_settings,
        query_service=query_service,
        quality_service=quality_service,
        faq_service=faq_service,
        knowledge_client=knowledge_client,
        quality_metrics_by_issue=quality_metrics_by_issue,
        enrich_quality_issue_display=enrich_quality_issue_display,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_sync_routes(
        app,
        resolved_settings=resolved_settings,
        sync_service=sync_service,
        run_sync_job=run_sync_job,
        current_actor=current_actor,
        require_capability=require_capability,
        faq_service=faq_service,
        query_service=query_service,
    )
    register_budget_routes(
        app,
        budget_service=budget_service,
        query_service=query_service,
        notification_dispatcher=notification_dispatcher,
        evaluate_all_budgets=evaluate_all_budgets,
        check_api_health_alerts=check_api_health_alerts,
        configured_targets=configured_targets,
        current_actor=current_actor,
        require_capability=require_capability,
    )

    register_prompt_poc_routes(
        app,
        resolved_settings=resolved_settings,
        query_service=query_service,
        prompt_service=prompt_service,
        example_service=example_service,
        current_actor=current_actor,
        require_capability=require_capability,
    )

    app.state.eval_harness_status = eval_harness_status
    app.state.governance_service = governance_service
    app.state.query_service = query_service
    app.state.faq_service = faq_service
    app.state.example_service = example_service
    app.state.quality_service = quality_service
    app.state.sync_service = sync_service
    app.state.budget_service = budget_service
    register_governance_routes(
        app,
        governance=governance_service,
        current_actor=current_actor,
        require_capability=require_capability,
        example_service=example_service,
        faq_service=faq_service,
        query_service=query_service,
        quality_service=quality_service,
        eval_harness_status=eval_harness_status,
    )

    app.include_router(
        build_knowledge_router(
            client=knowledge_client,
            current_actor=current_actor,
            enabled=resolved_settings.knowledge_bridge_enabled,
        ),
        prefix="/api/knowledge",
    )

    # Phase 3 feature-flag list remains available under the governed API.
    @app.get("/api/feature-flags")
    async def list_feature_flags(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.flags.read")
        return {"items": governance_service.list_flags(actor=actor)}

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(
            _render_index_html(),
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    portal_static = Path(__file__).resolve().parents[1] / "knowledge_portal" / "static"
    if portal_static.is_dir():
        app.mount(
            "/static/kp",
            StaticFiles(directory=portal_static),
            name="knowledge_portal_static",
        )

    @app.get("/knowledge-ui")
    @app.get("/knowledge-ui/")
    async def knowledge_ui() -> FileResponse:
        """Same-origin Knowledge Portal UI hosted inside the ops console."""
        return FileResponse(
            STATIC_DIR / "knowledge-ui.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.add_middleware(_NoStoreStaticCacheMiddleware)
    return app


app = create_app()
