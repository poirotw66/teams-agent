"""Governance HTTP route registration.

Request bodies, search extras, and model schedule helpers live in sibling
modules; this module owns the public registrar and re-exports body models.
"""

from __future__ import annotations

from fastapi import FastAPI

from .governance_audit_routes import register_audit_routes
from .governance_domain import GovernanceService
from .governance_flag_routes import register_flag_routes
from .governance_model_routes import register_model_routes
from .governance_model_schedule import run_model_schedule, scheduled_model_id
from .governance_policy_routes import register_policy_routes
from .governance_prompt_routes import register_prompt_routes
from .governance_role_routes import register_role_routes
from .governance_route_errors import register_governance_exception_handlers
from .governance_route_models import (
    FallbackBody,
    FlagCandidateBody,
    MaskingBody,
    ModelCandidateBody,
    PromptActivateBody,
    PromptApproveBody,
    PromptCanaryBody,
    PromptCanaryEvaluateBody,
    PromptCanaryStopBody,
    PromptCandidateBody,
    PromptRollbackBody,
    ReasonBody,
    RetentionBody,
    RevokeBody,
    RoleRequestBody,
)
from .governance_search_routes import register_search_routes

# Re-export body models for stable importers / OpenAPI discovery.
__all__ = [
    "FallbackBody",
    "FlagCandidateBody",
    "MaskingBody",
    "ModelCandidateBody",
    "PromptActivateBody",
    "PromptApproveBody",
    "PromptCanaryBody",
    "PromptCanaryEvaluateBody",
    "PromptCanaryStopBody",
    "PromptCandidateBody",
    "PromptRollbackBody",
    "ReasonBody",
    "RetentionBody",
    "RevokeBody",
    "RoleRequestBody",
    "register_governance_routes",
]


def register_governance_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    example_service,
    faq_service=None,
    query_service=None,
    quality_service=None,
    eval_harness_status=None,
) -> None:
    register_governance_exception_handlers(app)
    register_prompt_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
        example_service=example_service,
        eval_harness_status=eval_harness_status,
    )
    register_model_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
        query_service=query_service,
    )
    register_flag_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_role_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_policy_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_search_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
        example_service=example_service,
        faq_service=faq_service,
        query_service=query_service,
        quality_service=quality_service,
    )
    register_audit_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
    )


# Stable private aliases (historical underscore names).
_run_model_schedule = run_model_schedule
_scheduled_model_id = scheduled_model_id
