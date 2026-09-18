"""Pydantic request payloads for golden evaluation-set routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1)
    owner_unit_id: str
    behavior: Literal[
        "ANSWER_WITH_CITATION",
        "CLARIFY",
        "REFUSE",
        "HANDOFF",
        "TOOL_TASK",
    ] = "ANSWER_WITH_CITATION"
    reference_answer: str | None = None
    required_facts: list[dict[str, Any]] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    criticality: Literal["CRITICAL", "NORMAL"] = "NORMAL"
    source_type: Literal[
        "MANUAL",
        "QUALITY_CASE",
        "FAQ",
        "DOCUMENT",
        "CONVERSATION",
        "SYNTHETIC",
    ] = "MANUAL"
    source_id: str | None = None
    source_version_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RevisionCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    base_revision_id: str | None = None
    behavior: Literal[
        "ANSWER_WITH_CITATION",
        "CLARIFY",
        "REFUSE",
        "HANDOFF",
        "TOOL_TASK",
    ] | None = None
    reference_answer: str | None = None
    required_facts: list[dict[str, Any]] | None = None
    forbidden_claims: list[str] | None = None
    tags: list[str] | None = None
    criticality: Literal["CRITICAL", "NORMAL"] | None = None


class SubmitRevisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_etag: int = Field(ge=1)


class ReviewRevisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    reason: str = Field(min_length=1)
    expected_etag: int = Field(ge=1)


class RetireCasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)


class SetCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    owner_unit_ids: list[str] = Field(min_length=1)
    purpose: Literal["DEVELOPMENT", "HOLDOUT"] = "DEVELOPMENT"
    description: str = ""


class SetVersionDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_revision_ids: list[str] = Field(min_length=1)


class PublishSetVersionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_etag: int = Field(ge=1)


class ImportValidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    file_format: Literal["JSONL", "CSV"] = "JSONL"
    owner_unit_id: str


class ExportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set_id: str | None = None
    file_format: Literal["JSONL", "CSV"] = "JSONL"


class CandidateJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_refs: list[dict[str, Any]] = Field(min_length=1)
    target_types: list[str] = Field(default_factory=lambda: ["ANSWER_WITH_CITATION"])
    requested_count: int = Field(default=5, ge=1, le=100)
    owner_unit_id: str
    limits: dict[str, Any] = Field(default_factory=dict)
