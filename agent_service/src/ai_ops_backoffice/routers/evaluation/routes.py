"""Register all golden evaluation-set API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI

from ...evaluation_domain import (
    CandidateGenerationManager,
    EvaluationImportExportManager,
    EvaluationService,
)
from .candidates import register_candidate_routes
from .cases import register_case_routes
from .context import EvaluationRouteContext
from .imports_exports import register_import_export_routes
from .revisions import register_revision_routes
from .sets import register_set_routes


def register_evaluation_routes(
    app: FastAPI,
    *,
    evaluation_service: EvaluationService,
    import_export_manager: EvaluationImportExportManager,
    candidate_manager: CandidateGenerationManager,
    current_actor: Any,
    require_capability: Any,
) -> None:
    """Register HTTP routes for evaluation cases, sets, import/export, and candidates."""
    ctx = EvaluationRouteContext(
        evaluation_service=evaluation_service,
        import_export_manager=import_export_manager,
        candidate_manager=candidate_manager,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    router = APIRouter(prefix="/api/evaluations", tags=["Golden Eval Set"])
    register_case_routes(router, ctx)
    register_revision_routes(router, ctx)
    register_set_routes(router, ctx)
    register_import_export_routes(router, ctx)
    register_candidate_routes(router, ctx)
    app.include_router(router)
