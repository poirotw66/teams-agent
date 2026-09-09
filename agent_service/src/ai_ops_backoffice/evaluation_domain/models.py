from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.masking import MASKING_POLICY_VERSION

from .runner_models import CaseExecution, EvaluationRun, ReviewDecision

EvalBehaviorType = Literal[
    "ANSWER_WITH_CITATION",
    "CLARIFY",
    "REFUSE",
    "HANDOFF",
    "TOOL_TASK",
]

Criticality = Literal["CRITICAL", "NORMAL"]

ProvenanceSourceType = Literal[
    "MANUAL",
    "QUALITY_CASE",
    "FAQ",
    "DOCUMENT",
    "CONVERSATION",
    "SYNTHETIC",
]

RevisionStatus = Literal["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "RETIRED"]

SourceHealth = Literal["VALID", "NEEDS_REVIEW", "SOURCE_UNAVAILABLE"]

SetPurpose = Literal["DEVELOPMENT", "HOLDOUT"]

SetVersionStatus = Literal["DRAFT", "PUBLISHED", "RETIRED"]

CandidateJobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CriterionItem(StrictModel):
    criterion_id: str
    description: str
    is_mandatory: bool = True
    exact_match: str | None = None
    semantic_rubric: str | None = None


class EvaluationCriteria(StrictModel):
    required_facts: tuple[CriterionItem, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    reference_answer: str | None = None


class EvidenceItem(StrictModel):
    evidence_id: str
    source_type: Literal["FAQ", "DOCUMENT", "OTHER"]
    source_id: str
    version_id: str | None = None
    section: str | None = None
    text: str | None = None
    content_hash: str | None = None


class EvidenceRequirement(StrictModel):
    group_id: str
    items: tuple[EvidenceItem, ...]


class TurnSpec(StrictModel):
    turn_id: str
    user_query: str
    expected_behavior: EvalBehaviorType = "ANSWER_WITH_CITATION"
    criteria: EvaluationCriteria | None = None
    evidence: tuple[EvidenceRequirement, ...] = ()


class ToolConstraintsSpec(StrictModel):
    required_tools: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    max_calls: int | None = None
    parameter_constraints: dict[str, Any] = Field(default_factory=dict)


class ProvenanceSpec(StrictModel):
    source_type: ProvenanceSourceType
    source_id: str
    source_version_id: str | None = None
    source_correlation_id: str | None = None
    original_case_ref: str | None = None
    generator_model: str | None = None
    generator_prompt_version: str | None = None
    masking_policy_version: str = MASKING_POLICY_VERSION


def calculate_revision_content_hash(
    *,
    query: str,
    turns: tuple[TurnSpec, ...] = (),
    criteria: EvaluationCriteria,
    evidence: tuple[EvidenceRequirement, ...] = (),
    behavior: EvalBehaviorType,
    tool_constraints: ToolConstraintsSpec,
    tags: tuple[str, ...] = (),
    criticality: Criticality,
    provenance: ProvenanceSpec,
) -> str:
    canonical = {
        "query": query.strip(),
        "turns": [turn.model_dump(mode="json") for turn in turns],
        "criteria": criteria.model_dump(mode="json"),
        "evidence": [req.model_dump(mode="json") for req in evidence],
        "behavior": behavior,
        "tool_constraints": tool_constraints.model_dump(mode="json"),
        "tags": sorted(tags),
        "criticality": criticality,
        "provenance": provenance.model_dump(mode="json"),
    }
    dumped = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def calculate_manifest_hash(revision_pairs: list[tuple[str, str]]) -> str:
    """Computes an immutable manifest hash from sorted (revision_id, content_hash) pairs."""
    sorted_pairs = sorted(revision_pairs, key=lambda pair: pair[0])
    canonical_list = [f"{rev_id}:{content_hash}" for rev_id, content_hash in sorted_pairs]
    serialized = "\n".join(canonical_list)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class CaseRevision(StrictModel):
    revision_id: str
    case_id: str
    revision_number: int = Field(ge=1)
    schema_version: str = "v1"
    query: str
    turns: tuple[TurnSpec, ...] = ()
    persona_fixture_ref: str | None = None
    criteria: EvaluationCriteria = Field(default_factory=EvaluationCriteria)
    evidence: tuple[EvidenceRequirement, ...] = ()
    behavior: EvalBehaviorType = "ANSWER_WITH_CITATION"
    tool_constraints: ToolConstraintsSpec = Field(default_factory=ToolConstraintsSpec)
    tags: tuple[str, ...] = ()
    criticality: Criticality = "NORMAL"
    provenance: ProvenanceSpec
    status: RevisionStatus = "DRAFT"
    source_health: SourceHealth = "VALID"
    etag: int = Field(ge=1)
    content_hash: str
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None
    retired_by: str | None = None
    retired_at: datetime | None = None


class EvalCase(StrictModel):
    case_id: str
    tenant_id: str
    owner_unit_id: str
    title: str = Field(min_length=1, max_length=200)
    current_revision_id: str
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalSet(StrictModel):
    set_id: str
    tenant_id: str
    owner_unit_ids: tuple[str, ...]
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    purpose: SetPurpose = "DEVELOPMENT"
    lead_owner: str
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    is_active: bool = True


class EvalSetVersion(StrictModel):
    set_version_id: str
    set_id: str
    version: int = Field(ge=1)
    case_revision_ids: tuple[str, ...]
    coverage_stats: dict[str, Any] = Field(default_factory=dict)
    manifest_hash: str
    status: SetVersionStatus = "DRAFT"
    published_by: str | None = None
    published_at: datetime | None = None
    created_by: str
    created_at: datetime
    etag: int = Field(ge=1)


class EvaluationAuditEvent(StrictModel):
    audit_id: str
    entity_type: str
    entity_id: str
    action: str
    actor_id: str
    actor_role: str
    owner_unit_id: str
    tenant_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    occurred_at: datetime
    correlation_id: str | None = None


class EvaluationIdempotencyRecord(StrictModel):
    key: str
    action: str
    request_fingerprint: str
    result: dict[str, Any]


class CandidateGenerationJob(StrictModel):
    job_id: str
    tenant_id: str
    owner_unit_id: str
    source_refs: tuple[dict[str, Any], ...]
    target_types: tuple[str, ...]
    requested_count: int
    limits: dict[str, Any] = Field(default_factory=dict)
    status: CandidateJobStatus = "QUEUED"
    created_candidate_case_ids: tuple[str, ...] = ()
    used_tokens: int = 0
    estimated_cost_usd: float = 0.0
    error_message: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class ImportValidationResult(StrictModel):
    is_valid: bool
    total_rows: int
    valid_rows: int
    error_rows: int
    errors: tuple[dict[str, Any], ...] = ()
    similar_warnings: tuple[dict[str, Any], ...] = ()
    staged_import_id: str | None = None


class EvaluationState(StrictModel):
    cases: tuple[EvalCase, ...] = ()
    revisions: tuple[CaseRevision, ...] = ()
    sets: tuple[EvalSet, ...] = ()
    set_versions: tuple[EvalSetVersion, ...] = ()
    candidate_jobs: tuple[CandidateGenerationJob, ...] = ()
    runs: tuple[EvaluationRun, ...] = ()
    case_executions: tuple[CaseExecution, ...] = ()
    review_decisions: tuple[ReviewDecision, ...] = ()
    audits: tuple[EvaluationAuditEvent, ...] = ()
    idempotency: tuple[EvaluationIdempotencyRecord, ...] = ()
