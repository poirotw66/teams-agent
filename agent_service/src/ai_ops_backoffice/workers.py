"""Background workers for AI Ops backoffice app lifespan."""

from __future__ import annotations

from operations_core.access import ActorContext

from .workers_budget import build_check_api_health_alerts, build_evaluate_all_budgets
from .workers_lifespan import build_lifespan
from .workers_retention import run_scheduled_retention_sweep
from .workers_sync import build_run_sync_job

__all__ = [
    "install_background_runtime",
    "run_scheduled_retention_sweep",
]


def install_background_runtime(
    *,
    resolved_settings,
    query_service,
    sync_service,
    budget_service,
    notification_dispatcher,
    knowledge_transport,
    sync_transport,
    example_service=None,
    quality_service=None,
    governance_service=None,
    job_worker=None,
    eval_scheduler=None,
    freshness_tracker=None,
):
    """Build sync worker callbacks and FastAPI lifespan."""

    sync_worker = ActorContext(
        user_id="ai-ops-sync-worker",
        display_name="AI Ops Sync Worker",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(),
    )

    run_sync_job = build_run_sync_job(
        resolved_settings=resolved_settings,
        query_service=query_service,
        sync_service=sync_service,
        budget_service=budget_service,
        notification_dispatcher=notification_dispatcher,
        knowledge_transport=knowledge_transport,
        sync_transport=sync_transport,
        sync_worker=sync_worker,
    )
    check_api_health_alerts = build_check_api_health_alerts(
        query_service=query_service,
        budget_service=budget_service,
        notification_dispatcher=notification_dispatcher,
    )
    evaluate_all_budgets = build_evaluate_all_budgets(
        resolved_settings=resolved_settings,
        query_service=query_service,
        budget_service=budget_service,
        notification_dispatcher=notification_dispatcher,
        check_api_health_alerts=check_api_health_alerts,
    )
    lifespan = build_lifespan(
        resolved_settings=resolved_settings,
        query_service=query_service,
        sync_service=sync_service,
        budget_service=budget_service,
        example_service=example_service,
        quality_service=quality_service,
        governance_service=governance_service,
        job_worker=job_worker,
        eval_scheduler=eval_scheduler,
        freshness_tracker=freshness_tracker,
        sync_worker=sync_worker,
        evaluate_all_budgets=evaluate_all_budgets,
    )

    return sync_worker, run_sync_job, check_api_health_alerts, evaluate_all_budgets, lifespan
