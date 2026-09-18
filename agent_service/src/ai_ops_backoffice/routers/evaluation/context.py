"""Shared route context for golden evaluation-set handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...evaluation_domain import (
    CandidateGenerationManager,
    EvaluationImportExportManager,
    EvaluationService,
)


@dataclass(frozen=True)
class EvaluationRouteContext:
    """Collaborators and auth hooks shared by evaluation route modules."""

    evaluation_service: EvaluationService
    import_export_manager: EvaluationImportExportManager
    candidate_manager: CandidateGenerationManager
    current_actor: Callable[..., Any]
    require_capability: Callable[..., Any]
