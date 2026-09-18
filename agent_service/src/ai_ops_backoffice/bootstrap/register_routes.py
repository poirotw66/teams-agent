"""Register Backoffice HTTP routers from a built container."""

from __future__ import annotations

from fastapi import FastAPI

from ai_ops_backoffice.bootstrap.container import BackofficeContainer
from ai_ops_backoffice.bootstrap.ui import register_static_ui_routes
from ai_ops_backoffice.governance_routes import register_governance_routes
from ai_ops_backoffice.knowledge_bridge import build_knowledge_router
from ai_ops_backoffice.routers import (
    register_budget_routes,
    register_console_routes,
    register_evaluation_routes,
    register_evaluation_run_routes,
    register_example_routes,
    register_faq_routes,
    register_gate_routes,
    register_ops_read_routes,
    register_prompt_poc_routes,
    register_quality_routes,
    register_sync_routes,
    register_tool_fixture_routes,
    register_workbench_routes,
)


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
    deps = container.deps
    register_ops_read_routes(
        app,
        resolved_settings=container.settings,
        query_service=container.query_service,
        governance_service=container.governance_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
        audit_read=deps.audit_read,
        export_rate_limiter=container.export_rate_limiter,
        example_service=container.example_service,
        quality_service=container.quality_service,
        sync_service=container.sync_service,
        budget_service=container.budget_service,
    )
    register_faq_routes(
        app,
        resolved_settings=container.settings,
        query_service=container.query_service,
        faq_service=container.faq_service,
        quality_service=container.quality_service,
        quality_metrics_by_issue=deps.quality_metrics_by_issue,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
        audit_read=deps.audit_read,
    )
    register_example_routes(
        app,
        resolved_settings=container.settings,
        query_service=container.query_service,
        example_service=container.example_service,
        faq_service=container.faq_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
    register_quality_routes(
        app,
        resolved_settings=container.settings,
        query_service=container.query_service,
        quality_service=container.quality_service,
        faq_service=container.faq_service,
        knowledge_client=container.knowledge_client,
        quality_metrics_by_issue=deps.quality_metrics_by_issue,
        enrich_quality_issue_display=deps.enrich_quality_issue_display,
        evaluation_service=container.evaluation_service,
        evaluation_run_service=container.evaluation_run_service,
        quality_gate_service=container.quality_gate_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
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
    register_evaluation_routes(
        app,
        evaluation_service=container.evaluation_service,
        import_export_manager=container.import_export_manager,
        candidate_manager=container.candidate_manager,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
    register_evaluation_run_routes(
        app,
        run_service=container.evaluation_run_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
    register_tool_fixture_routes(
        app,
        fixture_service=container.tool_fixture_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
    register_gate_routes(
        app,
        gate_service=container.quality_gate_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
    register_governance_routes(
        app,
        governance=container.governance_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
        example_service=container.example_service,
        faq_service=container.faq_service,
        query_service=container.query_service,
        quality_service=container.quality_service,
        eval_harness_status=container.eval_harness_status,
    )
    register_console_routes(
        app,
        quality_service=container.quality_service,
        knowledge_client=container.knowledge_client,
        evaluation_service=container.evaluation_service,
        evaluation_run_service=container.evaluation_run_service,
        quality_gate_service=container.quality_gate_service,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
    register_workbench_routes(
        app,
        resolved_settings=container.settings,
        query_service=container.query_service,
        knowledge_client=container.knowledge_client,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
    )
    app.include_router(
        build_knowledge_router(
            client=container.knowledge_client,
            current_actor=deps.current_actor,
            enabled=container.settings.knowledge_bridge_enabled,
        ),
        prefix="/api/knowledge",
    )
    register_static_ui_routes(
        app,
        container.settings,
        current_actor=deps.current_actor,
        require_capability=deps.require_capability,
        governance_service=container.governance_service,
    )
