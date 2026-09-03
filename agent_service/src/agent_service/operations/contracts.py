from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1
METRICS_DEFINITION_VERSION = "v1"
MASKING_POLICY_VERSION = "v2"
DEFAULT_TIMEZONE = "Asia/Taipei"

Environment = Literal["dev", "test", "poc", "prod"]
DataClassification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
ChannelScope = Literal["personal", "channel", "group_chat", "playground"]
IssueTypeStatus = Literal["DRAFT", "ACTIVE", "DEPRECATED"]
ClassificationSource = Literal[
    "MODEL", "FAQ_MAPPING", "DOCUMENT_MAPPING", "MANUAL", "FALLBACK"
]

OperationalEventType = Literal[
    "conversation.started",
    "turn.received",
    "issue.extracted",
    "issue.classified",
    "route.selected",
    "faq.answered",
    "knowledge.retrieved",
    "knowledge.answered",
    "answer.completed",
    "feedback.recorded",
    "handoff.offered",
    "handoff.started",
    "handoff.completed",
    "handoff.cancelled",
    "ticket.created",
    "ticket.failed",
    "usage.recorded",
    "request.failed",
    "knowledge.release.activated",
    "config.changed",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IssueTypeRecord(StrictModel):
    issue_type_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parent_issue_type_id: str | None = None
    owner_unit_id: str = Field(min_length=1)
    status: IssueTypeStatus = "ACTIVE"
    taxonomy_version: str = Field(min_length=1)
    effective_at: str | None = None
    retired_at: str | None = None
    created_by: str | None = None
    approved_by: str | None = None


class IssueTaxonomyDocument(StrictModel):
    taxonomy_version: str
    generated_at: str
    issue_types: list[IssueTypeRecord]


class OperationalEvent(StrictModel):
    event_id: str = Field(min_length=1)
    event_type: OperationalEventType
    schema_version: int = SCHEMA_VERSION
    occurred_at: datetime
    ingested_at: datetime | None = None
    environment: Environment = "dev"
    tenant_id: str | None = None
    team_id: str | None = None
    channel_scope: ChannelScope = "playground"
    conversation_id: str | None = None
    turn_id: str | None = None
    request_id: str | None = None
    correlation_id: str = Field(min_length=1)
    issue_occurrence_id: str | None = None
    issue_type_id: str | None = None
    taxonomy_version: str | None = None
    actor_ref: str | None = None
    data_classification: DataClassification = "INTERNAL"
    retention_expires_at: datetime | None = None
    masking_policy_version: str = MASKING_POLICY_VERSION
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditEventRecord(StrictModel):
    audit_id: str
    actor_id: str
    actor_role: str
    action: str
    target_type: str
    target_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    result: Literal["SUCCESS", "FAILED", "DENIED"] = "SUCCESS"
    correlation_id: str | None = None
    occurred_at: datetime
    environment: Environment = "dev"
    retention_policy: str = "audit-default"
    retention_expires_at: datetime | None = None


class CursorPage(StrictModel):
    items: list[Any]
    next_cursor: str | None = None
    has_more: bool = False


def utc_now() -> datetime:
    return datetime.now(UTC)
