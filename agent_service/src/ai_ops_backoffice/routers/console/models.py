"""Pydantic response models for console aggregation routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class WorkItemAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    route: str


class WorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    workflow: str
    source_type: str
    source_id: str
    title: str
    owner_unit_id: str
    assignee_id: str | None = None
    source_status: str
    step: str
    next_action: WorkItemAction
    blocked_reason: str | None = None
    due_at: str | None = None
    updated_at: str
    revision: str


class WorkItemsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: list[WorkItem]
    next_cursor: str | None = None
    total: int
    snapshot_id: str
    generated_at: str
    partial: bool
    sources: dict[str, str]


class WorkSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    total: int
    by_bucket: dict[str, int]
    by_workflow: dict[str, int]
    sources: dict[str, str]
    snapshot_id: str
    generated_at: str


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_type: str
    source_id: str
    version_hash: str | None = None
    relation: str
    occurred_at: str | None = None
    retrieved_at: str
    validity: Literal["valid", "stale", "unknown", "revoked"]


class WorkflowStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    status: Literal["pending", "current", "completed", "skipped", "failed"]


class WorkflowDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    id: str
    title: str
    status: str
    stages: list[WorkflowStage]
    evidence_refs: list[EvidenceRef]
    allowed_actions: list[str]
    return_route: str
