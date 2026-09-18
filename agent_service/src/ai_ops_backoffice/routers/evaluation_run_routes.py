from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, FastAPI

from operations_core.access import ActorContext

from ..evaluation_domain import EvaluationRunService
from .evaluation_run_create_routes import register_evaluation_run_create_routes
from .evaluation_run_read_routes import (
    register_evaluation_run_read_routes,
    register_evaluation_run_review_routes,
)


def register_evaluation_run_routes(
    app: FastAPI,
    run_service: EvaluationRunService,
    current_actor: Callable[..., ActorContext],
    require_capability: Callable[[ActorContext, str], None],
) -> None:
    router = APIRouter(prefix="/api/evaluations", tags=["Evaluation Runs"])
    register_evaluation_run_create_routes(router, run_service, current_actor, require_capability)
    register_evaluation_run_read_routes(router, run_service, current_actor, require_capability)
    register_evaluation_run_review_routes(router, run_service, current_actor, require_capability)
    app.include_router(router)
