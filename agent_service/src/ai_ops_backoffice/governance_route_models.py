"""Request body models for governance HTTP routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "FallbackBody",
    "FlagCandidateBody",
    "MaskingBody",
    "ModelCandidateBody",
    "PromptActivateBody",
    "PromptApproveBody",
    "PromptCanaryBody",
    "PromptCanaryEvaluateBody",
    "PromptCanaryStopBody",
    "PromptCandidateBody",
    "PromptRollbackBody",
    "ReasonBody",
    "RetentionBody",
    "RevokeBody",
    "RoleRequestBody",
]


class PromptCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    taxonomy_version: str
    knowledge_release_id: str | None = None


class PromptApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)
    policy_exception_reason: str | None = None
    policy_exception_expires_at: datetime | None = None
    approved: bool | None = None


class PromptCanaryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    percent: int = Field(ge=1, le=99)
    environment: str = "prod"
    reason: str = Field(min_length=3)


class PromptCanaryStopBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)
    rollback: bool = False


class PromptCanaryEvaluateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_rate: float = Field(ge=0, le=1)
    negative_feedback_rate: float = Field(ge=0, le=1)
    handoff_rate: float = Field(ge=0, le=1)
    safety_alerts: int = Field(default=0, ge=0)
    sample_size: int = Field(ge=0)


class PromptActivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)
    emergency: bool = False


class PromptRollbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)


class ModelCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_id: str = "issue-extractor-model"
    provider: str
    model_id: str
    component: str = "issue-extractor"
    temperature: float = Field(default=0.0, ge=0, le=1)
    max_output_tokens: int = Field(default=2048, ge=1, le=8192)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    retry: int = Field(default=1, ge=0, le=3)
    secret_ref: str
    region: str = "asia-east1"
    pricing_version: str = "v1"
    fallback_model_id: str | None = None
    fallback_on: tuple[str, ...] = ()
    change_reason: str = Field(min_length=3)


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)


class FallbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: Literal["TIMEOUT", "RATE_LIMIT", "UNAVAILABLE"]


class FlagCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag_id: str
    value: str
    environment: str = "lab"
    expires_at: datetime | None = None
    percent: int | None = Field(default=None, ge=1, le=100)
    reason: str = Field(min_length=3)


class RoleRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_principal: str
    target_role: str | None = None
    add_capabilities: tuple[str, ...] = ()
    remove_capabilities: tuple[str, ...] = ()
    reason: str = Field(min_length=3)


class RevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal: str
    reason: str = Field(min_length=3)


class RetentionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = "operational-events"
    ttl_days: int = Field(ge=1, le=3650)
    migration_plan: str = Field(min_length=3)
    reason: str = Field(min_length=3)


class MaskingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=3)
