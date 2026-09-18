"""Internal service wiring helpers for Backoffice composition."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import httpx
from fastapi import FastAPI

from agent_service.graph import build_chat_model
from agent_service.operations.policy_runtime import (
    PolicyRuntime,
    configure_policy_runtime,
    get_policy_runtime,
)
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
from ai_ops_backoffice.budget_domain import BudgetService
from ai_ops_backoffice.runtime_hooks import get_portal_app_factory
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
from ai_ops_backoffice.faq_domain import FaqDomainService, FaqValidationError
from ai_ops_backoffice.governance_domain import GovernanceService
from ai_ops_backoffice.governance_domain.eval_runtime import (
    build_agent_sandbox_workflow_executor,
    resolve_backoffice_eval_harness,
)
from ai_ops_backoffice.knowledge_bridge import KnowledgePortalClient
from ai_ops_backoffice.notification_dispatcher import NotificationDispatcher
from ai_ops_backoffice.prompt_domain import PromptPocService
from ai_ops_backoffice.quality_domain import QualityService
from ai_ops_backoffice.services.export_auth_store import FileBackedExportAuthorizationResolver
from ai_ops_backoffice.services.export_authorization import GovernanceRevocationAuthority
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.settings import BackofficeSettings
from ai_ops_backoffice.sync_domain import SyncService

logger = logging.getLogger(__name__)

_VALID_NOTIFICATION_CHANNELS = frozenset({"TEAMS", "EMAIL", "NOTIFICATION_CENTER"})


class ActiveFaqTaxonomy:
    def __init__(self, query_service: BackofficeQueryService) -> None:
        self._query_service = query_service

    def require_active(self, issue_type_id: str) -> None:
        issue_type = self._query_service.taxonomy.get(issue_type_id)
        if issue_type is None or issue_type.status != "ACTIVE":
            raise FaqValidationError(f"inactive issue type: {issue_type_id}")


@dataclass
class EvaluationStack:
    evaluation_service: EvaluationService
    import_export_manager: EvaluationImportExportManager
    candidate_manager: CandidateGenerationManager
    eval_runner: EvaluationRunner
    evaluation_run_service: EvaluationRunService
    tool_fixture_service: ToolFixtureService
    quality_gate_service: QualityGateService
    job_repository: object
    job_worker: ExecutionJobWorker
    eval_scheduler: EvalScheduler


def parse_budget_notification_targets(settings: BackofficeSettings) -> dict[str, str]:
    configured_targets: dict[str, str] = {}
    for entry in settings.budget_notification_targets:
        target_id, separator, channel = entry.partition("=")
        normalized_channel = channel.strip().upper()
        if (
            not separator
            or not target_id.strip()
            or normalized_channel not in _VALID_NOTIFICATION_CHANNELS
        ):
            raise ValueError(f"Invalid budget notification target configuration: {entry}")
        configured_targets[target_id.strip()] = normalized_channel
    return configured_targets


def build_prompt_service(
    settings: BackofficeSettings,
    prompt_repository: object,
) -> PromptPocService:
    prompt_effective_at = (
        datetime.fromisoformat(settings.prompt_active_effective_at.replace("Z", "+00:00"))
        if settings.prompt_active_effective_at
        else None
    )
    if prompt_effective_at is not None and prompt_effective_at.utcoffset() is None:
        raise ValueError("AI_OPS_PROMPT_ACTIVE_EFFECTIVE_AT requires a timezone")
    return PromptPocService(
        prompt_repository,
        active_effective_at=prompt_effective_at,
    )


def maybe_build_in_process_portal(
    settings: BackofficeSettings,
    *,
    knowledge_transport: httpx.AsyncBaseTransport | None,
    delegation_secret: str | None,
    portal_app_factory: Callable[..., FastAPI] | None = None,
) -> tuple[FastAPI | None, httpx.AsyncBaseTransport | None, str | None]:
    portal_app: FastAPI | None = None
    resolved_secret = delegation_secret
    resolved_transport = knowledge_transport
    factory = portal_app_factory or get_portal_app_factory()
    if (
        knowledge_transport is None
        and settings.knowledge_bridge_enabled
        and getattr(settings, "knowledge_in_process", True)
        and factory is not None
    ):
        try:
            from knowledge_portal.settings import PortalSettings

            if not resolved_secret:
                resolved_secret = secrets.token_hex(32)

            portal_settings = PortalSettings.from_env()
            portal_settings = replace(
                portal_settings,
                delegation_secret=resolved_secret,
                require_service_token_with_delegation=bool(settings.knowledge_service_token),
            )
            portal_app = factory(portal_settings)
            resolved_transport = httpx.ASGITransport(app=portal_app)
            logger.info("In-process Knowledge Portal initialized successfully.")
        except Exception:
            logger.exception(
                "Failed to initialize in-process Knowledge Portal; falling back to remote URL."
            )
    return portal_app, resolved_transport, resolved_secret


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
            query_service.export_jobs._store_path / "export_auth_registry.json",
            authority=export_authority,
        )
    )


def configure_governance_policy_runtime(
    query_service: BackofficeQueryService,
    governance_service: GovernanceService,
) -> None:
    existing_runtime = get_policy_runtime()
    policy_settings = (
        existing_runtime._settings
        if existing_runtime is not None
        else query_service._runtime.settings
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
        return build_chat_model(requested)

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
        return build_chat_model(RagSettings.from_env().model)
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
