from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_service.operations.masking import mask_text, redact_secrets

LifecycleStatus = Literal[
    "DRAFT",
    "CANDIDATE",
    "EVALUATED",
    "APPROVED",
    "CANARY",
    "ACTIVE",
    "RETIRED",
    "REJECTED",
]
EvalStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "INCOMPLETE"]
FlagType = Literal["boolean", "enum", "percentage"]
RoleChangeStatus = Literal["REQUESTED", "APPROVED", "REJECTED", "REVOKED"]
TargetType = Literal[
    "PROMPT",
    "MODEL",
    "FLAG",
    "ROLE_MAPPING",
    "RETENTION",
    "MASKING",
    "SEARCH",
    "AUDIT",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class PromptRecord(StrictModel):
    prompt_id: str
    component: str
    display_name: str
    description: str
    active_version_id: str | None = None
    canary_version_id: str | None = None
    previous_healthy_version_id: str | None = None
    etag: int = Field(ge=1)


class PromptVersion(StrictModel):
    version_id: str
    prompt_id: str
    version: str
    status: LifecycleStatus
    template: str
    content_hash: str
    input_schema_version: str
    output_schema_version: str
    taxonomy_version: str
    dataset_version: str | None = None
    faq_release_id: str | None = None
    knowledge_release_id: str | None = None
    model_id: str
    secret_refs: tuple[str, ...] = ()
    created_by: str
    created_at: datetime
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    activated_by: str | None = None
    activated_at: datetime | None = None
    change_reason: str | None = None
    rollback_of_version_id: str | None = None
    eval_run_id: str | None = None
    canary_percent: int | None = Field(default=None, ge=1, le=99)
    canary_environment: str | None = None
    canary_stopped: bool = False
    policy_exception_reason: str | None = None
    policy_exception_expires_at: datetime | None = None

    @field_validator("change_reason", "policy_exception_reason")
    @classmethod
    def _mask_reason(cls, value: str | None) -> str | None:
        return mask_text(value).text if value else value


class EvalCaseResult(StrictModel):
    case_id: str
    category: str
    critical: bool
    passed: bool
    detail: str


class EvalRun(StrictModel):
    run_id: str
    status: EvalStatus
    target_type: TargetType
    target_id: str
    version_id: str
    baseline_version_id: str | None
    dataset_version: str
    taxonomy_version: str
    knowledge_release_id: str | None
    model_id: str
    runner_version: str
    metric_version: str
    manifest_hash: str
    critical_passed: bool
    quality_passed: bool
    case_results: tuple[EvalCaseResult, ...]
    accuracy: float = Field(ge=0, le=1)
    baseline_accuracy: float | None = Field(default=None, ge=0, le=1)
    estimated_cost_usd: float = Field(ge=0)
    baseline_cost_usd: float | None = Field(default=None, ge=0)
    latency_ms: float = Field(ge=0)
    baseline_latency_ms: float | None = Field(default=None, ge=0)
    created_by: str
    created_at: datetime
    completed_at: datetime | None = None
    # Gate separation: status=execution finished; critical=safety; quality=floor+flows.
    quality_gate_version: str = ""
    reproducibility: dict[str, Any] = Field(default_factory=dict)


class ModelConfigRecord(StrictModel):
    config_id: str
    component: str
    active_version_id: str | None = None
    previous_healthy_version_id: str | None = None
    etag: int = Field(ge=1)


class ModelConfigVersion(StrictModel):
    version_id: str
    config_id: str
    provider: str
    model_id: str
    component: str
    status: LifecycleStatus
    temperature: float = Field(ge=0, le=1)
    max_output_tokens: int = Field(ge=1, le=8192)
    timeout_seconds: int = Field(ge=1, le=120)
    retry: int = Field(ge=0, le=3)
    secret_ref: str
    region: str
    pricing_version: str
    fallback_model_id: str | None = None
    fallback_on: tuple[str, ...] = ()
    max_attempts: int = Field(default=2, ge=1, le=5)
    content_hash: str
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    activated_by: str | None = None
    activated_at: datetime | None = None
    eval_run_id: str | None = None
    change_reason: str | None = None

    @field_validator("change_reason")
    @classmethod
    def _mask_reason(cls, value: str | None) -> str | None:
        return mask_text(value).text if value else value


class FlagRecord(StrictModel):
    flag_id: str
    description: str
    owner: str
    flag_type: FlagType
    safety_locked: bool = False
    default_value: str
    active_version_id: str | None = None
    etag: int = Field(ge=1)


class FlagVersion(StrictModel):
    version_id: str
    flag_id: str
    status: LifecycleStatus
    value: str
    environment: str
    audience: str = "all"
    percent: int | None = Field(default=None, ge=1, le=100)
    effective_at: datetime
    expires_at: datetime | None = None
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    activated_by: str | None = None
    activated_at: datetime | None = None
    change_reason: str | None = None

    @field_validator("change_reason")
    @classmethod
    def _mask_reason(cls, value: str | None) -> str | None:
        return mask_text(value).text if value else value


class RoleMappingChange(StrictModel):
    change_id: str
    target_principal: str
    target_role: str | None = None
    add_capabilities: tuple[str, ...] = ()
    remove_capabilities: tuple[str, ...] = ()
    status: RoleChangeStatus
    requested_by: str
    requested_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: str
    expires_at: datetime | None = None

    @field_validator("reason")
    @classmethod
    def _mask_reason(cls, value: str) -> str:
        return mask_text(value).text


class RetentionPolicyVersion(StrictModel):
    version_id: str
    policy_id: str
    status: LifecycleStatus
    ttl_days: int = Field(ge=1, le=3650)
    migration_plan: str
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    activated_by: str | None = None
    activated_at: datetime | None = None
    change_reason: str | None = None


class MaskingPolicyVersion(StrictModel):
    version_id: str
    policy_version: str
    status: LifecycleStatus
    rules_hash: str
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    activated_by: str | None = None
    activated_at: datetime | None = None
    change_reason: str | None = None


class GovernanceAuditEvent(StrictModel):
    audit_id: str
    action: str
    actor_id: str
    actor_role: str
    target_type: TargetType
    target_id: str
    version_id: str | None = None
    result: Literal["SUCCESS", "DENIED", "FAILED"] = "SUCCESS"
    reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    correlation_id: str | None = None
    environment: str = "lab"
    occurred_at: datetime

    @field_validator("reason")
    @classmethod
    def _mask_reason(cls, value: str | None) -> str | None:
        return mask_text(value).text if value else value

    @field_validator("before", "after")
    @classmethod
    def _redact(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return redact_secrets(value) if value is not None else None


class IdempotencyRecord(StrictModel):
    key: str
    action: str
    request_fingerprint: str
    result: dict[str, Any]
    created_at: datetime


class GovernanceState(StrictModel):
    revision: int = 0
    prompts: tuple[PromptRecord, ...] = ()
    prompt_versions: tuple[PromptVersion, ...] = ()
    eval_runs: tuple[EvalRun, ...] = ()
    model_configs: tuple[ModelConfigRecord, ...] = ()
    model_versions: tuple[ModelConfigVersion, ...] = ()
    flags: tuple[FlagRecord, ...] = ()
    flag_versions: tuple[FlagVersion, ...] = ()
    role_changes: tuple[RoleMappingChange, ...] = ()
    retention_policies: tuple[RetentionPolicyVersion, ...] = ()
    masking_policies: tuple[MaskingPolicyVersion, ...] = ()
    audits: tuple[GovernanceAuditEvent, ...] = ()
    idempotency: tuple[IdempotencyRecord, ...] = ()
    revoked_principals: tuple[str, ...] = ()
    granted_capabilities: dict[str, tuple[str, ...]] = Field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(UTC)


def replace_model(model: Any, **changes: Any) -> Any:
    return type(model).model_validate({**model.model_dump(), **changes})
