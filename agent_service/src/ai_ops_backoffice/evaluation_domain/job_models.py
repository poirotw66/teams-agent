from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

JobState = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "PARTIAL"]


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionJob(StrictModel):
    tenant_id: str
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    logical_key: str
    state: JobState = "QUEUED"
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    lease_owner: str | None = None
    lease_until: datetime | None = None
    heartbeat_at: datetime | None = None
    checkpoint_ref: str | None = None
    cancel_requested_at: datetime | None = None
    last_error: str | None = None
    fencing_token: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime


class JobCheckpoint(StrictModel):
    job_id: str
    run_id: str
    completed_case_ids: tuple[str, ...] = ()
    completed_execution_ids: tuple[str, ...] = ()
    accumulated_cost_usd: float = 0.0
    accumulated_tokens: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)
