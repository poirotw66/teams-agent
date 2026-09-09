from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TargetSide = Literal["BASELINE", "CANDIDATE"]
RunStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLING", "CANCELLED"]
ExecutionStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
MetricStatus = Literal["PASS", "FAIL", "INCONCLUSIVE", "NOT_APPLICABLE"]
FailureClassification = Literal[
    "RETRIEVAL_MISS",
    "ANSWER_INCORRECT",
    "CITATION_UNSUPPORTED",
    "HALLUCINATION",
    "ACL_LEAK",
    "SAFETY_VIOLATION",
    "TIMEOUT",
    "UNEXPECTED_ERROR",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TargetManifest(StrictModel):
    target_id: str
    target_side: TargetSide
    app_revision: str = "v1"
    prompt_version: str = "default"
    model_id: str = "gemini-2.5-flash"
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    knowledge_release_id: str | None = None
    faq_version_id: str | None = None
    retriever_config: dict[str, Any] = Field(default_factory=dict)
    persona_fixture_id: str | None = None
    acl_policy: str = "STRICT"
    environment: str = "test"
    manifest_hash: str


class MetricResult(StrictModel):
    metric_id: str
    version: str = "v1"
    score: float | None = None
    pass_status: MetricStatus = "PASS"
    applicability: bool = True
    reason: str | None = None
    evidence_refs: tuple[str, ...] = ()


class CaseExecution(StrictModel):
    execution_id: str
    run_id: str
    case_revision_id: str
    case_id: str
    target_side: TargetSide
    attempt: int = Field(default=1, ge=1)
    status: ExecutionStatus = "QUEUED"
    answer: str | None = None
    retrieved_evidence: tuple[dict[str, Any], ...] = ()
    trace_ref: dict[str, Any] = Field(default_factory=dict)
    metric_results: tuple[MetricResult, ...] = ()
    failure_classification: FailureClassification | None = None
    passed: bool | None = None
    is_critical_failure: bool = False
    used_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    error_detail: str | None = None


class ReviewDecision(StrictModel):
    decision_id: str
    run_id: str
    case_execution_id: str
    metric_id: str
    original_decision: str
    new_decision: MetricStatus
    reason: str
    reviewer_id: str
    reviewed_at: datetime


class RunComparisonSummary(StrictModel):
    total_cases: int
    executed_cases: int
    judged_cases: int
    baseline_passed_cases: int
    candidate_passed_cases: int
    pass_rate: float | None = None
    coverage: float = 0.0
    regressions: tuple[str, ...] = ()
    fixes: tuple[str, ...] = ()
    critical_failures: tuple[str, ...] = ()
    inconclusive_cases: tuple[str, ...] = ()
    actual_cost_usd: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0


class RunPreflightResult(StrictModel):
    is_valid: bool
    blocking_errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    resolved_baseline_manifest: TargetManifest | None = None
    resolved_candidate_manifest: TargetManifest | None = None
    case_count: int = 0
    estimated_cost_usd: float = 0.0
    estimated_duration_seconds: float = 0.0


class EvaluationRun(StrictModel):
    run_id: str
    tenant_id: str
    owner_unit_id: str
    set_version_id: str
    baseline_manifest: TargetManifest
    candidate_manifest: TargetManifest
    mode: Literal["OFFLINE_BENCHMARK", "REAL_RAG"] = "REAL_RAG"
    status: RunStatus = "QUEUED"
    runner_version: str = "ge2-runner-v1"
    metric_version: str = "ge2-metrics-v1"
    judge_version: str = "ge2-judge-v1"
    limits: dict[str, Any] = Field(default_factory=dict)
    repetitions: int = Field(default=1, ge=1, le=5)
    requested_by: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: RunComparisonSummary | None = None
    cancel_reason: str | None = None
    error_message: str | None = None
    actual_cost_usd: float = 0.0
    actual_tokens: int = 0
    correlation_id: str | None = None
