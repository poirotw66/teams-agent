from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GatePolicyStatus = Literal["DRAFT", "APPROVED", "ACTIVE", "RETIRED"]
GateMode = Literal["REPORT_ONLY", "ENFORCE"]
CriticalRule = Literal["ZERO_TOLERANCE", "ALLOW_WITH_EXCEPTION"]
GateDecisionStatus = Literal["PASS", "FAIL", "EXCEPTION_APPROVED"]
ScheduleFrequency = Literal["HOURLY", "DAILY", "WEEKLY", "ON_CHANGE"]


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GatePolicyVersion(StrictModel):
    policy_id: str
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    mode: GateMode = "REPORT_ONLY"
    target_types: tuple[str, ...] = ("PROMPT", "MODEL", "KNOWLEDGE", "RETRIEVER")
    environments: tuple[str, ...] = ("staging", "prod")
    required_set_version_ids: tuple[str, ...] = ()
    required_tags: tuple[str, ...] = ()
    minimum_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    critical_rule: CriticalRule = "ZERO_TOLERANCE"
    minimum_pass_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    max_regression_count: int = Field(default=0, ge=0)
    max_cost_usd: float | None = None
    max_latency_p95_ms: float | None = None
    validity_hours: int = Field(default=72, ge=1)
    status: GatePolicyStatus = "DRAFT"
    etag: int = Field(default=1, ge=1)
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None


class GatePolicy(StrictModel):
    policy_id: str
    tenant_id: str
    name: str
    current_version: int = Field(default=1, ge=1)
    active_version: int | None = None
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class GateException(StrictModel):
    exception_id: str
    decision_id: str
    reason: str
    requested_by: str
    requested_at: datetime
    approved_by_1: str | None = None
    approved_at_1: datetime | None = None
    approved_by_2: str | None = None
    approved_at_2: datetime | None = None
    expires_at: datetime
    is_active: bool = True
    disallowed_critical_failure: bool = False


class GateDecision(StrictModel):
    decision_id: str
    policy_id: str
    policy_version: int
    run_id: str
    target_manifest_hash: str
    decision: GateDecisionStatus
    mode_at_evaluation: GateMode
    tenant_id: str = "default"
    suite_versions: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    result_digest: str = ""
    actor_id: str = "system"
    blocking_reasons: tuple[str, ...] = ()
    metrics_snapshot: dict[str, Any] = Field(default_factory=dict)
    valid_until: datetime
    is_valid: bool = True
    is_eval_eligible: bool = True
    exceptions: tuple[GateException, ...] = ()
    created_at: datetime


class SourceImpactResult(StrictModel):
    source_type: str
    source_id: str
    source_version: str | None = None
    affected_case_ids: tuple[str, ...] = ()
    affected_revision_ids: tuple[str, ...] = ()
    affected_set_version_ids: tuple[str, ...] = ()
    has_active_manifest_impact: bool = False
    requires_review_count: int = 0


class EvalSchedule(StrictModel):
    schedule_id: str
    tenant_id: str
    name: str
    set_version_id: str
    owner_unit_id: str = "IT Service Desk"
    timezone: str = "UTC"
    frequency: ScheduleFrequency = "DAILY"
    cron_expression: str | None = None
    next_due_at: datetime | None = None
    misfire_policy: Literal["COALESCE_LATEST", "RUN_ALL", "SKIP"] = "COALESCE_LATEST"
    target_selector: str = "CANDIDATE_LATEST"
    budget_limit_usd: float = Field(default=5.0, gt=0.0)
    target_refs: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    last_run_id: str | None = None
    last_run_at: datetime | None = None
    missed_count: int = 0
    revision: int = 1
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class QualityCaseLink(StrictModel):
    quality_case_id: str
    eval_case_id: str
    run_id: str
    execution_id: str
    root_cause: str
    status: Literal["OPEN", "IN_PROGRESS", "RESOLVED"] = "OPEN"
    resolution_run_id: str | None = None
    created_at: datetime
    updated_at: datetime


TargetType = Literal[
    "KNOWLEDGE",
    "FAQ",
    "PROMPT",
    "MODEL",
    "RETRIEVER",
    "AGENT_CONFIG",
]


class ActiveReleasePointer(StrictModel):
    pointer_id: str
    tenant_id: str = "default"
    environment: str = "prod"
    target_type: TargetType
    active_manifest_hash: str
    active_version_ref: str
    active_target_manifest: dict[str, Any] = Field(default_factory=dict)
    decision_id: str
    etag: int = Field(default=1, ge=1)
    updated_at: datetime
    updated_by: str
    previous_manifest_hash: str | None = None
    is_break_glass: bool = False
    break_glass_id: str | None = None


class BreakGlassRequest(StrictModel):
    break_glass_id: str
    tenant_id: str
    environment: str = "prod"
    target_type: TargetType
    candidate_manifest_hash: str
    reason: str
    authorized_by: str
    requested_by: str
    expires_at: datetime
    created_at: datetime
    is_used: bool = False


class ActivationAuditRecord(StrictModel):
    activation_id: str
    pointer_id: str
    tenant_id: str
    environment: str
    target_type: TargetType
    from_manifest_hash: str | None
    to_manifest_hash: str
    decision_id: str | None
    is_break_glass: bool = False
    break_glass_id: str | None = None
    activated_by: str
    activated_at: datetime


class ScheduleDispatchResult(StrictModel):
    dispatch_id: str
    schedule_id: str
    logical_key: str
    scheduled_at: datetime
    dispatched_at: datetime
    status: Literal["DISPATCHED", "SKIPPED_BUDGET", "SKIPPED_OVERLAP", "SKIPPED_MISFIRE", "DUPLICATE_IGNORED"]
    run_id: str | None = None
    estimated_cost_usd: float | None = None
    reason: str | None = None

