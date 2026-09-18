"""Register Backoffice HTTP routers from a built container."""

from __future__ import annotations

from fastapi import FastAPI

from ai_ops_backoffice.bootstrap.container import BackofficeContainer
from ai_ops_backoffice.bootstrap.register_eval_governance_routes import (
    register_eval_governance_routes,
)
from ai_ops_backoffice.bootstrap.register_ops_quality_routes import register_ops_quality_routes


def bind_app_state(app: FastAPI, container: BackofficeContainer) -> None:
    app.state.settings = container.settings
    app.state.eval_harness_status = container.eval_harness_status
    app.state.governance_service = container.governance_service
    app.state.query_service = container.query_service
    app.state.freshness_tracker = getattr(container.query_service, "_freshness_tracker", None)
    app.state.faq_service = container.faq_service
    app.state.example_service = container.example_service
    app.state.quality_service = container.quality_service
    app.state.sync_service = container.sync_service
    app.state.budget_service = container.budget_service
    app.state.evaluation_service = container.evaluation_service
    app.state.evaluation_run_service = container.evaluation_run_service
    app.state.eval_runner = container.eval_runner
    app.state.tool_fixture_service = container.tool_fixture_service
    app.state.quality_gate_service = container.quality_gate_service
    app.state.portal_app = container.portal_app
    app.state.knowledge_client = container.knowledge_client
    app.state.job_repository = container.job_repository
    app.state.job_worker = container.job_worker


def register_domain_routes(app: FastAPI, container: BackofficeContainer) -> None:
    register_ops_quality_routes(app, container)
    register_eval_governance_routes(app, container)
