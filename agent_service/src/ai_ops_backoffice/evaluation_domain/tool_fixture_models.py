from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .runner_models import MetricResult

ToolFixtureStatus = Literal["DRAFT", "APPROVED", "RETIRED"]


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MockResponseSpec(StrictModel):
    match_parameters: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    error_status: str | None = None
    error_message: str | None = None
    latency_ms: float = 0.0


def calculate_tool_fixture_hash(
    *,
    tool_name: str,
    input_schema: dict[str, Any],
    mock_responses: tuple[MockResponseSpec, ...],
    default_response: dict[str, Any],
    allowlist_enabled: bool,
    is_sandbox_safe: bool,
    is_mutation: bool,
) -> str:
    canonical = {
        "tool_name": tool_name.strip(),
        "input_schema": input_schema,
        "mock_responses": [resp.model_dump(mode="json") for resp in mock_responses],
        "default_response": default_response,
        "allowlist_enabled": allowlist_enabled,
        "is_sandbox_safe": is_sandbox_safe,
        "is_mutation": is_mutation,
    }
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ToolFixtureVersion(StrictModel):
    fixture_id: str
    version: int = Field(ge=1)
    schema_version: str = "v1"
    tool_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    mock_responses: tuple[MockResponseSpec, ...] = ()
    default_response: dict[str, Any] = Field(default_factory=dict)
    allowlist_enabled: bool = True
    is_sandbox_safe: bool = True
    is_mutation: bool = False
    content_hash: str
    status: ToolFixtureStatus = "DRAFT"
    etag: int = Field(default=1, ge=1)
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_reason: str | None = None


class ToolFixture(StrictModel):
    fixture_id: str
    tenant_id: str
    tool_name: str
    current_version: int = Field(ge=1)
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class ToolCallTrace(StrictModel):
    call_id: str
    parent_id: str | None = None
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    duration_ms: float = 0.0
    is_error: bool = False
    error_message: str | None = None
    retry_count: int = 0


class TurnExecutionTrace(StrictModel):
    turn_index: int
    turn_id: str
    user_query: str
    agent_response: str
    tool_calls: tuple[ToolCallTrace, ...] = ()
    metrics: tuple[MetricResult, ...] = ()
    passed: bool = True
    failure_reason: str | None = None


class TrajectoryTrace(StrictModel):
    execution_id: str
    case_id: str
    target_side: str
    turns: tuple[TurnExecutionTrace, ...] = ()
    failed_step_index: int | None = None
    failed_step_reason: str | None = None
    overall_passed: bool = True
