from __future__ import annotations

from .candidate_generator import CandidateGenerationManager
from .errors import (
    EvaluationAuditWriteError,
    EvaluationAuthorizationError,
    EvaluationDomainError,
    EvaluationIdempotencyConflictError,
    EvaluationNotFoundError,
    EvaluationTransitionError,
    EvaluationValidationError,
    EvaluationVersionConflictError,
)
from .import_export import EvaluationImportExportManager
from .manifest import ManifestResolver, calculate_target_manifest_hash
from .models import (
    CandidateGenerationJob,
    CaseRevision,
    CriterionItem,
    EvalBehaviorType,
    EvalCase,
    EvalSet,
    EvalSetVersion,
    EvaluationAuditEvent,
    EvaluationCriteria,
    EvaluationIdempotencyRecord,
    EvaluationState,
    EvidenceItem,
    EvidenceRequirement,
    ImportValidationResult,
    ProvenanceSpec,
    ToolConstraintsSpec,
    TurnSpec,
    calculate_manifest_hash,
    calculate_revision_content_hash,
)
from .repository import (
    EvaluationRepository,
    FileEvaluationRepository,
    InMemoryEvaluationRepository,
)
from .run_service import EvaluationRunService
from .runner import EvaluationRunner
from .runner_models import (
    CaseExecution,
    EvaluationRun,
    MetricResult,
    ReviewDecision,
    RunComparisonSummary,
    RunPreflightResult,
    TargetManifest,
)
from .scorer import EvaluationScorer
from .service import EvaluationService

__all__ = [
    "CandidateGenerationJob",
    "CandidateGenerationManager",
    "CaseExecution",
    "CaseRevision",
    "CriterionItem",
    "EvalBehaviorType",
    "EvalCase",
    "EvalSet",
    "EvalSetVersion",
    "EvaluationAuditEvent",
    "EvaluationAuditWriteError",
    "EvaluationAuthorizationError",
    "EvaluationCriteria",
    "EvaluationDomainError",
    "EvaluationIdempotencyConflictError",
    "EvaluationIdempotencyRecord",
    "EvaluationImportExportManager",
    "EvaluationNotFoundError",
    "EvaluationRepository",
    "EvaluationRun",
    "EvaluationRunService",
    "EvaluationRunner",
    "EvaluationScorer",
    "EvaluationService",
    "EvaluationState",
    "EvaluationTransitionError",
    "EvaluationValidationError",
    "EvaluationVersionConflictError",
    "EvidenceItem",
    "EvidenceRequirement",
    "FileEvaluationRepository",
    "ImportValidationResult",
    "InMemoryEvaluationRepository",
    "ManifestResolver",
    "MetricResult",
    "ProvenanceSpec",
    "ReviewDecision",
    "RunComparisonSummary",
    "RunPreflightResult",
    "TargetManifest",
    "ToolConstraintsSpec",
    "TurnSpec",
    "calculate_manifest_hash",
    "calculate_revision_content_hash",
    "calculate_target_manifest_hash",
]
