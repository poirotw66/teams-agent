"""Pydantic request payloads for quality-gate routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateGatePolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str
    name: str
    description: str = ""
    mode: Literal["REPORT_ONLY", "ENFORCE"] = "REPORT_ONLY"
    minimum_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_pass_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    max_regression_count: int = Field(default=0, ge=0)
    required_set_version_ids: list[str] | None = None


class CreatePolicyVersionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    mode: Literal["REPORT_ONLY", "ENFORCE"] = "REPORT_ONLY"
    minimum_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_pass_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    max_regression_count: int = Field(default=0, ge=0)
    required_set_version_ids: list[str] | None = None


class ActivatePolicyVersionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["REPORT_ONLY", "ENFORCE"] | None = None


class EvaluateDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str
    policy_version: int | None = None
    run_id: str
    target_manifest_hash: str


class RequestExceptionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    validity_hours: int = Field(default=24, ge=1, le=168)


class CreateSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_id: str
    name: str
    set_version_id: str
    frequency: Literal["HOURLY", "DAILY", "WEEKLY", "ON_CHANGE"] = "DAILY"
    budget_limit_usd: float = Field(default=5.0, gt=0.0)
    target_refs: dict[str, Any] = Field(default_factory=dict)


class UpdateSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_enabled: bool | None = None
    frequency: Literal["HOURLY", "DAILY", "WEEKLY", "ON_CHANGE"] | None = None
    budget_limit_usd: float | None = Field(default=None, gt=0.0)
    target_refs: dict[str, Any] | None = None


class VerifyReleasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_manifest_hash: str
    policy_id: str = "default-gate-policy"


class CreateQualityCasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_cause: str


class ActivateTargetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["KNOWLEDGE", "FAQ", "PROMPT", "AGENT", "ROUTER"]
    candidate_manifest: dict[str, Any]
    active_version_ref: str
    environment: str = "prod"
    policy_id: str = "default-gate-policy"
    expected_pointer_etag: int | None = None
    break_glass_id: str | None = None
