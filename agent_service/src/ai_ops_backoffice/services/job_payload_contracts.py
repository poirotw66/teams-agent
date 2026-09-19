"""Background job and Cloud Tasks typed payload contracts.

Provides explicit schema definition, validation, and serialization for:
- Export job request parameters (conversations, feedback, issues, costs, routes, knowledge)
- Sync background job dispatch payloads
- Document ingestion task payloads
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

JOB_PAYLOAD_SCHEMA_VERSION = 1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ConversationsExportParams(StrictModel):
    actor_ref: str | None = None
    user_id: str | None = None
    issue_type_id: str | None = None
    route: str | None = None
    conversation_id: str | None = None
    model: str | None = None
    has_feedback: bool | None = None
    handoff: bool | None = None
    channel_scope: str | None = None
    query: str | None = None
    source: str | None = None


class FeedbackExportParams(StrictModel):
    rating: int | None = None
    issue_type_id: str | None = None
    feedback_reason: str | None = None
    resolved_status: str | None = None
    handoff: bool | None = None
    model: str | None = None
    route: str | None = None


class IssuesExportParams(StrictModel):
    query: str | None = None


class CostsExportParams(StrictModel):
    model: str | None = None


class RoutesExportParams(StrictModel):
    issue_type_id: str | None = None
    route: str | None = None


class KnowledgeExportParams(StrictModel):
    status: str | None = None
    owner_unit_id: str | None = None
    query: str | None = None
    format_type: str | None = None


class OperationsExportParams(StrictModel):
    preset: str | None = None


EXPORT_PARAM_MODELS: dict[str, type[StrictModel]] = {
    "conversations": ConversationsExportParams,
    "feedback": FeedbackExportParams,
    "issues_summary": IssuesExportParams,
    "costs_summary": CostsExportParams,
    "routes_summary": RoutesExportParams,
    "knowledge_performance": KnowledgeExportParams,
    "operations_summary": OperationsExportParams,
}


def validate_export_request_params(export_type: str, raw_params: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and sanitize export request parameters based on export_type."""
    if not raw_params:
        return {}
    model_cls = EXPORT_PARAM_MODELS.get(export_type)
    if model_cls is None:
        return dict(raw_params)
    parsed = model_cls.model_validate(raw_params)
    return {k: v for k, v in parsed.model_dump().items() if v is not None}


class SyncTaskPayload(StrictModel):
    """Cloud Task or Background Worker payload for Sync jobs."""

    schema_version: int = JOB_PAYLOAD_SCHEMA_VERSION
    job_id: str = Field(min_length=1)
    action: str = "sync"
    scope_type: str = "ALL"
    scope_ids: tuple[str, ...] = ()
    correlation_id: str = ""
    dispatched_at: str | None = None


class IngestionTaskPayload(StrictModel):
    """Cloud Task payload for Document Ingestion worker jobs."""

    schema_version: int = JOB_PAYLOAD_SCHEMA_VERSION
    job_id: str = Field(min_length=1)
    action: str = "run"
    tenant_id: str = "default"
    dispatched_at: str | None = None


__all__ = [
    "JOB_PAYLOAD_SCHEMA_VERSION",
    "ConversationsExportParams",
    "CostsExportParams",
    "FeedbackExportParams",
    "IngestionTaskPayload",
    "IssuesExportParams",
    "KnowledgeExportParams",
    "OperationsExportParams",
    "RoutesExportParams",
    "SyncTaskPayload",
    "validate_export_request_params",
]
