"""Evaluation / governance / console / workbench route registration group."""

from __future__ import annotations

from fastapi import FastAPI

from ai_ops_backoffice.bootstrap.container import BackofficeContainer
from ai_ops_backoffice.bootstrap.ui import register_static_ui_routes
from ai_ops_backoffice.governance_routes import register_governance_routes
from ai_ops_backoffice.knowledge_bridge import build_knowledge_router
from ai_ops_backoffice.routers import (
    register_console_routes,
    register_evaluation_routes,
    register_evaluation_run_routes,
    register_gate_routes,
    register_tool_fixture_routes,
    register_workbench_routes,
)


def register_eval_governance_routes(app: FastAPI, container: BackofficeContainer) -> None:
    deps = container.deps
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
    # Agent knowledge sync BFF is registered once via register_ops_support_routes.
    app.include_router(
        build_knowledge_router(
            client=container.knowledge_client,
            current_actor=deps.current_actor,
            enabled=container.settings.knowledge_bridge_enabled,
            settings=container.settings,
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
