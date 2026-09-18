"""Backoffice composition root: construct services before route registration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI

from ai_ops_backoffice.bootstrap.wiring import (
    EvaluationStack,
    build_core_domain_services,
    build_evaluation_stack,
    build_governance_bundle,
    build_knowledge_client,
    build_ops_services,
)
from ai_ops_backoffice.budget_domain import BudgetService
from ai_ops_backoffice.deps import BackofficeDependencies, build_dependencies
from ai_ops_backoffice.evaluation_domain import (
    CandidateGenerationManager,
    EvaluationImportExportManager,
    EvaluationRunner,
    EvaluationRunService,
    EvaluationService,
    ExecutionJobWorker,
    QualityGateService,
    ToolFixtureService,
)
from ai_ops_backoffice.example_domain import ExampleService
from ai_ops_backoffice.faq_domain import FaqDomainService
from ai_ops_backoffice.governance_domain import GovernanceService
from ai_ops_backoffice.knowledge_bridge import KnowledgePortalClient
from ai_ops_backoffice.notification_dispatcher import NotificationDispatcher
from ai_ops_backoffice.prompt_domain import PromptPocService
from ai_ops_backoffice.quality_domain import QualityService
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.services.rate_limit import ExportRateLimiter
from ai_ops_backoffice.settings import BackofficeSettings
from ai_ops_backoffice.sync_domain import SyncService
from ai_ops_backoffice.workers import install_background_runtime


@dataclass
class BackofficeContainer:
    settings: BackofficeSettings
    query_service: BackofficeQueryService
    export_rate_limiter: ExportRateLimiter
    faq_service: FaqDomainService
    example_service: ExampleService
    quality_service: QualityService
    portal_app: FastAPI | None
    knowledge_client: KnowledgePortalClient
    sync_service: SyncService
    budget_service: BudgetService
    configured_targets: dict[str, str]
    notification_dispatcher: NotificationDispatcher
    prompt_service: PromptPocService
    governance_service: GovernanceService
    eval_harness_status: object
    evaluation_service: EvaluationService
    import_export_manager: EvaluationImportExportManager
    candidate_manager: CandidateGenerationManager
    eval_runner: EvaluationRunner
    evaluation_run_service: EvaluationRunService
    tool_fixture_service: ToolFixtureService
    quality_gate_service: QualityGateService
    job_repository: object
    job_worker: ExecutionJobWorker
    sync_worker: object
    run_sync_job: Callable[..., Any]
    check_api_health_alerts: Callable[..., Any]
    evaluate_all_budgets: Callable[..., Any]
    lifespan: Any
    deps: BackofficeDependencies


def _assemble_container(
    *,
    settings: BackofficeSettings,
    query_service: BackofficeQueryService,
    export_rate_limiter: ExportRateLimiter,
    faq_service: FaqDomainService,
    example_service: ExampleService,
    quality_service: QualityService,
    portal_app: FastAPI | None,
    knowledge_client: KnowledgePortalClient,
    sync_service: SyncService,
    budget_service: BudgetService,
    configured_targets: dict[str, str],
    notification_dispatcher: NotificationDispatcher,
    prompt_service: PromptPocService,
    governance_service: GovernanceService,
    eval_harness_status: object,
    evaluation: EvaluationStack,
    sync_worker: object,
    run_sync_job: Callable[..., Any],
    check_api_health_alerts: Callable[..., Any],
    evaluate_all_budgets: Callable[..., Any],
    lifespan: Any,
) -> BackofficeContainer:
    return BackofficeContainer(
        settings=settings,
        query_service=query_service,
        export_rate_limiter=export_rate_limiter,
        faq_service=faq_service,
        example_service=example_service,
        quality_service=quality_service,
        portal_app=portal_app,
        knowledge_client=knowledge_client,
        sync_service=sync_service,
        budget_service=budget_service,
        configured_targets=configured_targets,
        notification_dispatcher=notification_dispatcher,
        prompt_service=prompt_service,
        governance_service=governance_service,
        eval_harness_status=eval_harness_status,
        evaluation_service=evaluation.evaluation_service,
        import_export_manager=evaluation.import_export_manager,
        candidate_manager=evaluation.candidate_manager,
        eval_runner=evaluation.eval_runner,
        evaluation_run_service=evaluation.evaluation_run_service,
        tool_fixture_service=evaluation.tool_fixture_service,
        quality_gate_service=evaluation.quality_gate_service,
        job_repository=evaluation.job_repository,
        job_worker=evaluation.job_worker,
        sync_worker=sync_worker,
        run_sync_job=run_sync_job,
        check_api_health_alerts=check_api_health_alerts,
        evaluate_all_budgets=evaluate_all_budgets,
        lifespan=lifespan,
        deps=build_dependencies(
            resolved_settings=settings,
            query_service=query_service,
        ),
    )


def _install_runtime(
    settings: BackofficeSettings,
    *,
    query_service: BackofficeQueryService,
    sync_service: SyncService,
    budget_service: BudgetService,
    notification_dispatcher: NotificationDispatcher,
    knowledge_transport: httpx.AsyncBaseTransport | None,
    sync_transport: httpx.AsyncBaseTransport | None,
    example_service: ExampleService,
    quality_service: QualityService,
    governance_service: GovernanceService,
    evaluation: EvaluationStack,
) -> tuple[object, Callable[..., Any], Callable[..., Any], Callable[..., Any], Any]:
    return install_background_runtime(
        resolved_settings=settings,
        query_service=query_service,
        sync_service=sync_service,
        budget_service=budget_service,
        notification_dispatcher=notification_dispatcher,
        knowledge_transport=knowledge_transport,
        sync_transport=sync_transport,
        example_service=example_service,
        quality_service=quality_service,
        governance_service=governance_service,
        job_worker=evaluation.job_worker,
        eval_scheduler=evaluation.eval_scheduler,
        freshness_tracker=getattr(query_service, "_freshness_tracker", None),
    )


@dataclass(frozen=True)
class _DomainGraph:
    query_service: BackofficeQueryService
    faq_service: FaqDomainService
    example_service: ExampleService
    quality_service: QualityService
    portal_app: FastAPI | None
    knowledge_client: KnowledgePortalClient
    knowledge_transport: httpx.AsyncBaseTransport | None
    sync_service: SyncService
    configured_targets: dict[str, str]
    budget_service: BudgetService
    notification_dispatcher: NotificationDispatcher
    prompt_service: PromptPocService
    governance_service: GovernanceService
    eval_harness_status: object
    evaluation: EvaluationStack


def _build_domain_graph(
    settings: BackofficeSettings,
    *,
    eval_flow_harness: object | None,
    knowledge_transport: httpx.AsyncBaseTransport | None,
    notification_transport: httpx.AsyncBaseTransport | None,
    email_sender: Callable[[str, str, str], None] | None,
    eval_chat_model: object | None,
    eval_model_invoker: Callable[..., object] | None,
    eval_answering_fn: Callable[..., object] | None,
    portal_app_factory: Callable[..., FastAPI] | None,
) -> _DomainGraph:
    query_service = BackofficeQueryService(settings)
    faq_repository, faq_service, example_service, quality_service = build_core_domain_services(
        settings, query_service
    )
    portal_app, knowledge_client, knowledge_transport = build_knowledge_client(
        settings,
        knowledge_transport=knowledge_transport,
        portal_app_factory=portal_app_factory,
    )
    (
        sync_service,
        configured_targets,
        budget_service,
        notification_dispatcher,
        prompt_service,
        prompt_repository,
    ) = build_ops_services(
        settings,
        notification_transport=notification_transport,
        email_sender=email_sender,
    )
    governance_repository, governance_service, eval_harness_status = build_governance_bundle(
        settings, query_service, eval_flow_harness=eval_flow_harness
    )
    evaluation = build_evaluation_stack(
        settings,
        governance_repository=governance_repository,
        prompt_repository=prompt_repository,
        faq_repository=faq_repository,
        faq_service=faq_service,
        eval_chat_model=eval_chat_model,
        eval_model_invoker=eval_model_invoker,
        eval_answering_fn=eval_answering_fn,
    )
    return _DomainGraph(
        query_service=query_service,
        faq_service=faq_service,
        example_service=example_service,
        quality_service=quality_service,
        portal_app=portal_app,
        knowledge_client=knowledge_client,
        knowledge_transport=knowledge_transport,
        sync_service=sync_service,
        configured_targets=configured_targets,
        budget_service=budget_service,
        notification_dispatcher=notification_dispatcher,
        prompt_service=prompt_service,
        governance_service=governance_service,
        eval_harness_status=eval_harness_status,
        evaluation=evaluation,
    )


def build_backoffice_container(
    settings: BackofficeSettings,
    *,
    eval_flow_harness: object | None = None,
    knowledge_transport: httpx.AsyncBaseTransport | None = None,
    notification_transport: httpx.AsyncBaseTransport | None = None,
    sync_transport: httpx.AsyncBaseTransport | None = None,
    email_sender: Callable[[str, str, str], None] | None = None,
    eval_chat_model: object | None = None,
    eval_model_invoker: Callable[..., object] | None = None,
    eval_answering_fn: Callable[..., object] | None = None,
    portal_app_factory: Callable[..., FastAPI] | None = None,
) -> BackofficeContainer:
    graph = _build_domain_graph(
        settings,
        eval_flow_harness=eval_flow_harness,
        knowledge_transport=knowledge_transport,
        notification_transport=notification_transport,
        email_sender=email_sender,
        eval_chat_model=eval_chat_model,
        eval_model_invoker=eval_model_invoker,
        eval_answering_fn=eval_answering_fn,
        portal_app_factory=portal_app_factory,
    )
    sync_worker, run_sync_job, check_api_health_alerts, evaluate_all_budgets, lifespan = (
        _install_runtime(
            settings,
            query_service=graph.query_service,
            sync_service=graph.sync_service,
            budget_service=graph.budget_service,
            notification_dispatcher=graph.notification_dispatcher,
            knowledge_transport=graph.knowledge_transport,
            sync_transport=sync_transport,
            example_service=graph.example_service,
            quality_service=graph.quality_service,
            governance_service=graph.governance_service,
            evaluation=graph.evaluation,
        )
    )
    return _assemble_container(
        settings=settings,
        query_service=graph.query_service,
        export_rate_limiter=ExportRateLimiter(),
        faq_service=graph.faq_service,
        example_service=graph.example_service,
        quality_service=graph.quality_service,
        portal_app=graph.portal_app,
        knowledge_client=graph.knowledge_client,
        sync_service=graph.sync_service,
        budget_service=graph.budget_service,
        configured_targets=graph.configured_targets,
        notification_dispatcher=graph.notification_dispatcher,
        prompt_service=graph.prompt_service,
        governance_service=graph.governance_service,
        eval_harness_status=graph.eval_harness_status,
        evaluation=graph.evaluation,
        sync_worker=sync_worker,
        run_sync_job=run_sync_job,
        check_api_health_alerts=check_api_health_alerts,
        evaluate_all_budgets=evaluate_all_budgets,
        lifespan=lifespan,
    )
