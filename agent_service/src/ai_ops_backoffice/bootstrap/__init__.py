"""Composition-root helpers for AI Ops Backoffice."""

from __future__ import annotations

from ai_ops_backoffice.bootstrap.container import (
    BackofficeContainer,
    build_backoffice_container,
)
from ai_ops_backoffice.bootstrap.error_handlers import register_exception_handlers
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
from ai_ops_backoffice.bootstrap.ui import (
    STATIC_DIR,
    UI_ASSET_VERSION,
    register_static_ui_routes,
)

__all__ = [
    "STATIC_DIR",
    "UI_ASSET_VERSION",
    "BackofficeContainer",
    "build_backoffice_container",
    "build_budget_repository",
    "build_eval_prompt_resolver",
    "build_evaluation_repository",
    "build_example_repository",
    "build_faq_repository",
    "build_governance_repository",
    "build_job_repository",
    "build_prompt_poc_repository",
    "build_quality_gate_repository",
    "build_quality_repository",
    "build_sync_repository",
    "build_tool_fixture_repository",
    "register_exception_handlers",
    "register_static_ui_routes",
]
