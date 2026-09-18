"""Register all quality-gate API routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, FastAPI

from operations_core.access import ActorContext

from ...evaluation_domain.gate_service import QualityGateService
from .context import GateRouteContext
from .decisions import register_decision_routes
from .policies import register_policy_routes
from .policy_versions import register_policy_version_routes
from .release import register_release_routes
from .schedules import register_schedule_routes


def register_gate_routes(
    app: FastAPI,
    gate_service: QualityGateService,
    current_actor: Callable[..., ActorContext],
    require_capability: Callable[[ActorContext, str], None],
) -> None:
    """Register HTTP routes for gate policies, decisions, schedules, and release."""
    ctx = GateRouteContext(
        gate_service=gate_service,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    router = APIRouter(prefix="/api/evaluations", tags=["Quality Gates"])
    register_policy_routes(router, ctx)
    register_policy_version_routes(router, ctx)
    register_decision_routes(router, ctx)
    register_schedule_routes(router, ctx)
    register_release_routes(router, ctx)
    app.include_router(router)
