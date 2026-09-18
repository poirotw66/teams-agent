"""Ops / FAQ / example / quality route registration group."""

from __future__ import annotations

from fastapi import FastAPI

from ai_ops_backoffice.bootstrap.container import BackofficeContainer
from ai_ops_backoffice.routers import (
    register_example_routes,
    register_faq_routes,
    register_ops_read_routes,
    register_quality_routes,
)


def register_ops_core_routes(app: FastAPI, container: BackofficeContainer) -> None:
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
