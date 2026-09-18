"""Internal service wiring helpers for Backoffice composition."""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx
from fastapi import FastAPI

from agent_service.artifact_storage import GcsArtifactStorage, build_gcs_storage_client
from agent_service.graph import build_chat_model
from agent_service.operations.policy_runtime import (
    PolicyRuntime,
    configure_policy_runtime,
    get_policy_runtime,
)
from agent_service.operations.runtime import build_ops_runtime
from agent_service.settings import RagSettings
from ai_ops_backoffice.adapters.platform_ports import QualityGateReleaseChecker
from ai_ops_backoffice.bootstrap.eval_prompt import build_eval_prompt_resolver
from ai_ops_backoffice.bootstrap.repositories import (
    build_budget_repository,
    build_evaluation_repository,
    build_example_repository,
    build_faq_repository,
    build_governance_repository,
    build_job_repository,
    build_prompt_poc_repository,
    build_quality_gate_repository,
    build_quality_repository,
    build_sync_repository,
    build_tool_fixture_repository,
)
from ai_ops_backoffice.bootstrap.wiring_support import (
    ActiveFaqTaxonomy,
    EvaluationStack,
    build_prompt_service,
    maybe_build_in_process_portal,
    parse_budget_notification_targets,
)
from ai_ops_backoffice.budget_domain import BudgetService
from ai_ops_backoffice.evaluation_domain import (
    AgentBehaviorScorer,
    CandidateGenerationManager,
    EvalScheduler,
    EvaluationImportExportManager,
    EvaluationRunner,
    EvaluationRunService,
    EvaluationScorer,
    EvaluationService,
    ExecutionJobWorker,
    ManifestResolver,
    QualityGateService,
    ToolFixtureService,
)
from ai_ops_backoffice.example_domain import ExampleService
from ai_ops_backoffice.faq_domain import FaqDomainService
from ai_ops_backoffice.governance_domain import GovernanceService
from ai_ops_backoffice.governance_domain.eval_runtime import (
    build_agent_sandbox_workflow_executor,
    resolve_backoffice_eval_harness,
)
from ai_ops_backoffice.knowledge_bridge import KnowledgePortalClient
from ai_ops_backoffice.notification_dispatcher import NotificationDispatcher
from ai_ops_backoffice.ports.chat_model import (
    configure_chat_model_factory,
    get_chat_model_factory,
)
from ai_ops_backoffice.prompt_domain import PromptPocService
from ai_ops_backoffice.quality_domain import QualityService
from ai_ops_backoffice.services.export_auth_store import FileBackedExportAuthorizationResolver
from ai_ops_backoffice.services.export_authorization import GovernanceRevocationAuthority
from ai_ops_backoffice.services.freshness_service import FreshnessTracker
from ai_ops_backoffice.services.query_collaborators import configure_query_service_collaborators
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.settings import BackofficeSettings
from ai_ops_backoffice.sync_domain import SyncService
from knowledge_core.artifact_ports import ArtifactStorage, LocalFileArtifactStorage
from operations_core.settings import OpsSettings

logger = logging.getLogger(__name__)

__all__ = [
    "ActiveFaqTaxonomy",
    "EvaluationStack",
    "bind_export_authorization",
    "build_backoffice_artifact_storage",
    "build_backoffice_ops_runtime",
    "build_core_domain_services",
    "build_eval_model_factory",
    "build_eval_runner",
    "build_evaluation_stack",
    "build_governance_bundle",
    "build_knowledge_client",
    "build_ops_services",
    "build_prompt_service",
    "build_sandbox_adapter",
    "configure_governance_policy_runtime",
    "configure_query_service_agent_collaborators",
    "maybe_build_in_process_portal",
    "parse_budget_notification_targets",
]


def build_backoffice_ops_runtime(
    settings: OpsSettings,
    *,
    freshness_recorder: FreshnessTracker | None = None,
) -> object | None:
    """Compose Agent ops runtime for Backoffice query and governance wiring."""
    return build_ops_runtime(settings, freshness_recorder=freshness_recorder)


def build_backoffice_artifact_storage(settings: BackofficeSettings) -> ArtifactStorage:
    """Build FILE or GCS artifact storage for Backoffice source-trace paths."""
    artifact_backend = (getattr(settings, "artifact_storage_backend", None) or "FILE").upper()
    if artifact_backend == "GCS":
        bucket = getattr(settings, "artifact_gcs_bucket", None)
        if not bucket:
            raise ValueError(
                "AI_OPS_ARTIFACT_GCS_BUCKET (or AI_OPS_EXPORT_GCS_BUCKET) is required "
                "for GCS artifact storage."
            )
        return GcsArtifactStorage(
            bucket_name=bucket,
            client=build_gcs_storage_client(),
            allow_memory_fallback=False,
        )
    artifact_path = getattr(settings, "artifact_storage_path", None) or (
        settings.ops_store_path.parent / "sources" / "artifacts"
    )
    return LocalFileArtifactStorage(artifact_path)


def configure_query_service_agent_collaborators() -> None:
    """Register Agent-backed builders used by BackofficeQueryService defaults."""
    configure_query_service_collaborators(
        ops_runtime_builder=build_backoffice_ops_runtime,
        artifact_storage_builder=build_backoffice_artifact_storage,
    )


def configure_backoffice_chat_model_factory() -> None:
    """Register Agent graph build_chat_model for Backoffice judge/eval factories."""
    configure_chat_model_factory(build_chat_model)


configure_query_service_agent_collaborators()
configure_backoffice_chat_model_factory()


def bind_export_authorization(
    query_service: BackofficeQueryService,
    governance_repository: object,
) -> None:
    export_authority = GovernanceRevocationAuthority(
        lambda: set(governance_repository.load().revoked_principals)
    )
    query_service.bind_revocation_lookup(
        lambda: set(governance_repository.load().revoked_principals)
    )
    query_service.export_jobs.configure_authorization_resolver(
        FileBackedExportAuthorizationResolver(
            query_service.export_jobs.store_path / "export_auth_registry.json",
            authority=export_authority,
        )
    )


def configure_governance_policy_runtime(
    query_service: BackofficeQueryService,
    governance_service: GovernanceService,
) -> None:
    existing_runtime = get_policy_runtime()
    policy_settings = (
        existing_runtime.settings
        if existing_runtime is not None
        else query_service.runtime_settings
    )
    configure_policy_runtime(
        PolicyRuntime(settings=policy_settings, governance=governance_service)
    )


def build_eval_model_factory() -> Callable[[str], object | None]:
    def _eval_model_factory(model_id: str) -> object | None:
        requested = str(model_id or "").strip()
        if not requested:
            return None
        # Fail closed: never silently substitute the environment default model.
        return get_chat_model_factory()(requested)

    return _eval_model_factory


def build_sandbox_adapter(
    *,
    tool_fixture_service: ToolFixtureService,
    eval_model_factory: Callable[[str], object | None],
    eval_prompt_resolver: Callable[[str], str | None],
    faq_repository: object,
) -> object | None:
    try:
        from ai_ops_backoffice.evaluation_domain import RealAgentSandboxAdapter

        return RealAgentSandboxAdapter(
            tool_fixture_service,
            workflow_executor=build_agent_sandbox_workflow_executor(
                model_factory=eval_model_factory,
                prompt_resolver=eval_prompt_resolver,
                faq_repository=faq_repository,
            ),
        )
    except Exception as sandbox_err:  # pragma: no cover - optional live model deps
        logging.getLogger(__name__).warning(
            "AGENT_SANDBOX formal workflow unavailable: %s", sandbox_err
        )
        return None


def build_core_domain_services(
    settings: BackofficeSettings,
    query_service: BackofficeQueryService,
) -> tuple[object, FaqDomainService, ExampleService, QualityService]:
    taxonomy = ActiveFaqTaxonomy(query_service)
    faq_repository = build_faq_repository(settings)
    faq_service = FaqDomainService(
        faq_repository,
        taxonomy=taxonomy,
        artifact_dir=settings.faq_artifact_dir,
    )
    example_service = ExampleService(
        build_example_repository(settings),
        taxonomy=taxonomy,
    )
    quality_service = QualityService(build_quality_repository(settings))
    return faq_repository, faq_service, example_service, quality_service


def build_knowledge_client(
    settings: BackofficeSettings,
    *,
    knowledge_transport: httpx.AsyncBaseTransport | None,
    portal_app_factory: Callable[..., FastAPI] | None = None,
) -> tuple[FastAPI | None, KnowledgePortalClient, httpx.AsyncBaseTransport | None]:
    portal_app, resolved_transport, delegation_secret = maybe_build_in_process_portal(
        settings,
        knowledge_transport=knowledge_transport,
        delegation_secret=settings.knowledge_delegation_secret,
        portal_app_factory=portal_app_factory,
    )
    knowledge_client = KnowledgePortalClient(
        base_url=settings.knowledge_internal_url
        or settings.knowledge_portal_url
        or "http://inprocess-portal",
        service_token=settings.knowledge_service_token,
        delegation_secret=delegation_secret,
        auth_mode=settings.knowledge_auth_mode,
        timeout_seconds=settings.knowledge_timeout_seconds,
        transport=resolved_transport,
    )
    return portal_app, knowledge_client, resolved_transport


def build_ops_services(
    settings: BackofficeSettings,
    *,
    notification_transport: httpx.AsyncBaseTransport | None,
    email_sender: Callable[[str, str, str], None] | None,
) -> tuple[SyncService, dict[str, str], BudgetService, NotificationDispatcher, PromptPocService, object]:
    sync_service = SyncService(build_sync_repository(settings))
    configured_targets = parse_budget_notification_targets(settings)
    budget_service = BudgetService(
        build_budget_repository(settings),
        notification_targets=configured_targets,
    )
    notification_dispatcher = NotificationDispatcher(
        settings,
        budget_service,
        http_transport=notification_transport,
        email_sender=email_sender,
    )
    prompt_repository = build_prompt_poc_repository(settings)
    prompt_service = build_prompt_service(settings, prompt_repository)
    return (
        sync_service,
        configured_targets,
        budget_service,
        notification_dispatcher,
        prompt_service,
        prompt_repository,
    )


def build_governance_bundle(
    settings: BackofficeSettings,
    query_service: BackofficeQueryService,
    *,
    eval_flow_harness: object | None,
) -> tuple[object, GovernanceService, object]:
    governance_repository = build_governance_repository(settings)
    resolved_eval_harness, eval_harness_status = resolve_backoffice_eval_harness(
        eval_flow_harness  # type: ignore[arg-type]
    )
    governance_service = GovernanceService(
        governance_repository,
        eval_flow_harness=resolved_eval_harness,
    )
    bind_export_authorization(query_service, governance_repository)
    configure_governance_policy_runtime(query_service, governance_service)
    return governance_repository, governance_service, eval_harness_status


def resolve_eval_chat_model(
    *,
    eval_chat_model: object | None,
    eval_model_invoker: Callable[..., object] | None,
    eval_answering_fn: Callable[..., object] | None,
) -> object | None:
    if eval_answering_fn is None and eval_chat_model is None and eval_model_invoker is None:
        return get_chat_model_factory()(RagSettings.from_env().model)
    return eval_chat_model


def build_eval_runner(
    settings: BackofficeSettings,
    *,
    eval_repository: object,
    tool_fixture_service: ToolFixtureService,
    governance_repository: object,
    prompt_repository: object,
    faq_repository: object,
    eval_chat_model: object | None,
    eval_model_invoker: Callable[..., object] | None,
    eval_answering_fn: Callable[..., object] | None,
) -> tuple[EvaluationRunner, EvaluationScorer, object]:
    releases_dir = getattr(settings, "knowledge_release_dir", None) or (
        settings.ops_store_path.parent.parent / "releases"
    )
    eval_scorer = EvaluationScorer()
    # Formal app always enforces strict REAL_RAG: no synthetic answer fallback.
    eval_model_factory = build_eval_model_factory()
    eval_prompt_resolver = build_eval_prompt_resolver(
        governance_repository, prompt_repository
    )
    resolved_eval_chat_model = resolve_eval_chat_model(
        eval_chat_model=eval_chat_model,
        eval_model_invoker=eval_model_invoker,
        eval_answering_fn=eval_answering_fn,
    )
    sandbox_adapter = build_sandbox_adapter(
        tool_fixture_service=tool_fixture_service,
        eval_model_factory=eval_model_factory,
        eval_prompt_resolver=eval_prompt_resolver,
        faq_repository=faq_repository,
    )
    eval_runner = EvaluationRunner(
        eval_repository,
        scorer=eval_scorer,
        agent_scorer=AgentBehaviorScorer(),
        tool_fixture_service=tool_fixture_service,
        answering_fn=eval_answering_fn,
        releases_dir=releases_dir,
        strict_real_rag=True,
        chat_model=resolved_eval_chat_model,
        model_invoker=eval_model_invoker,
        model_factory=eval_model_factory if eval_answering_fn is None else None,
        prompt_resolver=eval_prompt_resolver if eval_answering_fn is None else None,
        sandbox_adapter=sandbox_adapter,
    )
    return eval_runner, eval_scorer, releases_dir


def build_evaluation_stack(
    settings: BackofficeSettings,
    *,
    governance_repository: object,
    prompt_repository: object,
    faq_repository: object,
    faq_service: FaqDomainService,
    eval_chat_model: object | None,
    eval_model_invoker: Callable[..., object] | None,
    eval_answering_fn: Callable[..., object] | None,
) -> EvaluationStack:
    eval_repository = build_evaluation_repository(settings)
    tool_fixture_service = ToolFixtureService(
        repository=build_tool_fixture_repository(settings)
    )
    gate_repository = build_quality_gate_repository(settings)
    job_repository = build_job_repository(settings)
    evaluation_service = EvaluationService(
        eval_repository,
        default_tenant_id=settings.deployment_tenant_id,
    )
    eval_runner, eval_scorer, releases_dir = build_eval_runner(
        settings,
        eval_repository=eval_repository,
        tool_fixture_service=tool_fixture_service,
        governance_repository=governance_repository,
        prompt_repository=prompt_repository,
        faq_repository=faq_repository,
        eval_chat_model=eval_chat_model,
        eval_model_invoker=eval_model_invoker,
        eval_answering_fn=eval_answering_fn,
    )
    job_worker = ExecutionJobWorker(
        job_repository=job_repository,
        runner=eval_runner,
        run_service=None,  # bound below after EvaluationRunService is constructed
    )
    evaluation_run_service = EvaluationRunService(
        eval_repository,
        manifest_resolver=ManifestResolver(eval_repository, releases_dir=releases_dir),
        runner=eval_runner,
        scorer=eval_scorer,
        job_repository=job_repository,
    )
    job_worker.set_run_service(evaluation_run_service)
    quality_gate_service = QualityGateService(
        eval_repository=eval_repository,
        gate_repository=gate_repository,
    )
    faq_service.set_release_gate_checker(QualityGateReleaseChecker(quality_gate_service))
    return EvaluationStack(
        evaluation_service=evaluation_service,
        import_export_manager=EvaluationImportExportManager(evaluation_service),
        candidate_manager=CandidateGenerationManager(evaluation_service),
        eval_runner=eval_runner,
        evaluation_run_service=evaluation_run_service,
        tool_fixture_service=tool_fixture_service,
        quality_gate_service=quality_gate_service,
        job_repository=job_repository,
        job_worker=job_worker,
        eval_scheduler=EvalScheduler(
            gate_repository=gate_repository,
            eval_repository=eval_repository,
            run_service=evaluation_run_service,
            gate_service=quality_gate_service,
        ),
    )
