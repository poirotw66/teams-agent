"""Sync / budget / prompt route registration group."""

from __future__ import annotations

from fastapi import FastAPI

from ai_ops_backoffice.bootstrap.container import BackofficeContainer
from ai_ops_backoffice.routers import (
    register_budget_routes,
    register_prompt_poc_routes,
    register_sync_routes,
)


def register_ops_support_routes(app: FastAPI, container: BackofficeContainer) -> None:
    deps = container.deps
    register_sync_routes(
        app,
        resolved_settings=container.settings,
        sync_service=container.sync_service,
        run_sync_job=container.run_sync_job,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
        faq_service=container.faq_service,
        query_service=container.query_service,
    )
    register_budget_routes(
        app,
        budget_service=container.budget_service,
        query_service=container.query_service,
        notification_dispatcher=container.notification_dispatcher,
        evaluate_all_budgets=container.evaluate_all_budgets,
        check_api_health_alerts=container.check_api_health_alerts,
        configured_targets=container.configured_targets,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
    register_prompt_poc_routes(
        app,
        resolved_settings=container.settings,
        query_service=container.query_service,
        prompt_service=container.prompt_service,
        example_service=container.example_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
