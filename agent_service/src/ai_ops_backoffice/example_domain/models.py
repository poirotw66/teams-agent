from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import MASKING_POLICY_VERSION, mask_text, redact_secrets

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)



class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class ExampleRecord(StrictModel):
    example_id: str
    source_type: Literal["FAQ", "DOCUMENT", "CONVERSATION", "MANUAL"]
    source_id: str
    source_version_id: str | None = None
    source_correlation_id: str | None = None
    owner_unit_id: str
    text: str = Field(min_length=1, max_length=4000)
    expected_issue_type_id: str
    expected_route: Literal["FAQ", "KNOWLEDGE", "TICKET", "HANDOFF"]
    label: Literal["POSITIVE", "NEGATIVE"]
    reason: str | None = None
    status: Literal["DRAFT", "VERIFIED", "REJECTED", "RETIRED"] = "DRAFT"
    etag: int = Field(ge=1)
    dataset_version: str | None = None
    masking_policy_version: str = MASKING_POLICY_VERSION
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    verified_by: str | None = None
    verified_at: datetime | None = None
    retired_by: str | None = None
    retired_at: datetime | None = None

class ExampleAuditEvent(StrictModel):
    audit_id: str
    example_id: str
    action: str
    actor_id: str
    actor_role: str
    owner_unit_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    occurred_at: datetime
    correlation_id: str | None = None

class ExampleIdempotencyRecord(StrictModel):
    key: str
    action: str
    request_fingerprint: str
    result: dict[str, Any]

class ExampleState(StrictModel):
    examples: tuple[ExampleRecord, ...] = ()
    audits: tuple[ExampleAuditEvent, ...] = ()
    idempotency: tuple[ExampleIdempotencyRecord, ...] = ()

