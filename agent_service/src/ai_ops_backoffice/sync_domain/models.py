from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import mask_text

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqVersionConflictError,
)



class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class SyncJob(StrictModel):
    job_id: str
    scope_type: Literal["ALL", "FAQ", "DOCUMENT", "FAILED"]
    scope_ids: tuple[str, ...] = ()
    scope_key: str
    requested_by: str
    owner_unit_id: str
    reason: str
    status: Literal[
        "QUEUED", "VALIDATING", "BUILDING", "VERIFYING", "COMPLETED", "FAILED", "CANCELLED"
    ] = "QUEUED"
    current_stage: str = "QUEUED"
    progress_percent: int = Field(default=0, ge=0, le=100)
    checkpoint_stage: str | None = None
    document_count: int = 0
    warnings: tuple[str, ...] = ()
    error_summary: str | None = None
    correlation_id: str
    target_release: str | None = None
    index_setting_version: str | None = None
    artifact_uri: str | None = None
    retry_of_job_id: str | None = None
    retry_checkpoint_stage: str | None = None
    etag: int = Field(default=1, ge=1)
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

class SyncAuditEvent(StrictModel):
    audit_id: str
    job_id: str
    action: str
    actor_id: str
    actor_role: str
    owner_unit_id: str
    reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    occurred_at: datetime

class SyncIdempotency(StrictModel):
    key: str
    actor_id: str
    fingerprint: str
    job_id: str

class SyncState(StrictModel):
    revision: int = 0
    jobs: tuple[SyncJob, ...] = ()
    audits: tuple[SyncAuditEvent, ...] = ()
    idempotency: tuple[SyncIdempotency, ...] = ()


Mutation = Callable[[SyncState], tuple[SyncState, dict[str, Any]]]

