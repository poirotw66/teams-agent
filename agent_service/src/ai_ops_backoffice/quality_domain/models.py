from __future__ import annotations

import hashlib
import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import mask_text, redact_secrets




class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class QualityCandidate(StrictModel):
    candidate_id: str
    source_type: Literal["EVENT", "MANUAL", "CLUSTER"]
    case_type: Literal[
        "NO_ANSWER",
        "LOW_CONFIDENCE",
        "NEGATIVE_FEEDBACK",
        "HANDOFF",
        "KNOWLEDGE_GAP",
        "OTHER",
    ]
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(max_length=4000)
    issue_type_id: str | None = None
    question_cluster_id: str | None = None
    owner_unit_id: str
    source_event_ids: tuple[str, ...] = ()
    conversation_refs: tuple[str, ...] = ()
    faq_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    frequency: int = Field(default=1, ge=1)
    negative_rate: float = Field(default=0, ge=0, le=1)
    handoff_rate: float = Field(default=0, ge=0, le=1)
    estimated_cost_impact: float = Field(default=0, ge=0)
    status: Literal["OPEN", "MERGED", "REJECTED"] = "OPEN"
    merged_case_id: str | None = None
    etag: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime

class QualityCase(StrictModel):
    case_id: str
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(max_length=4000)
    case_type: Literal[
        "NO_ANSWER",
        "LOW_CONFIDENCE",
        "NEGATIVE_FEEDBACK",
        "HANDOFF",
        "KNOWLEDGE_GAP",
        "OTHER",
    ]
    issue_type_id: str | None = None
    question_cluster_id: str | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    owner_unit_id: str
    assignee_id: str | None = None
    status: Literal[
        "NEW",
        "TRIAGED",
        "IN_PROGRESS",
        "WAITING_REVIEW",
        "OBSERVING",
        "RESOLVED",
        "WONT_FIX",
        "DUPLICATE",
    ] = "NEW"
    source_candidate_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    conversation_refs: tuple[str, ...] = ()
    faq_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    frequency: int = Field(default=1, ge=1)
    negative_rate: float = Field(default=0, ge=0, le=1)
    handoff_rate: float = Field(default=0, ge=0, le=1)
    estimated_cost_impact: float = Field(default=0, ge=0)
    target_due_at: datetime | None = None
    resolution_type: str | None = None
    resolution_note: str | None = None
    etag: int = Field(default=1, ge=1)
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    resolved_at: datetime | None = None
    observation_started_at: datetime | None = None
    observation_baseline: dict[str, float] | None = None
    observation_latest: dict[str, float] | None = None

class QuestionCluster(StrictModel):
    cluster_id: str
    cluster_key: str
    revision: int = Field(ge=1)
    status: Literal["CANDIDATE", "ACCEPTED", "REJECTED", "SUPERSEDED"] = "CANDIDATE"
    name: str = Field(min_length=1, max_length=240)
    representative_question: str = Field(min_length=1, max_length=4000)
    owner_unit_id: str
    source_candidate_ids: tuple[str, ...]
    issue_type_distribution: dict[str, int]
    frequency: int = Field(ge=1)
    # Not embedding/semantic clustering — honest analytics grouping only.
    grouping_method: Literal["OWNER_UNIT_ISSUE_TYPE"] = "OWNER_UNIT_ISSUE_TYPE"
    parent_cluster_ids: tuple[str, ...] = ()
    created_by: str
    created_at: datetime

class QualityAuditEvent(StrictModel):
    audit_id: str
    target_type: Literal["QUALITY_CANDIDATE", "QUALITY_CASE", "QUESTION_CLUSTER"]
    target_id: str
    action: str
    actor_id: str
    actor_role: str
    owner_unit_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    occurred_at: datetime

class QualityState(StrictModel):
    revision: int = 0
    candidates: tuple[QualityCandidate, ...] = ()
    cases: tuple[QualityCase, ...] = ()
    clusters: tuple[QuestionCluster, ...] = ()
    audits: tuple[QualityAuditEvent, ...] = ()


Mutation = Callable[[QualityState], tuple[QualityState, dict[str, Any]]]

