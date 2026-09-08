from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .faq_domain import FaqContent


class ExportRequest(BaseModel):
    export_type: str = Field(default="operations_summary")
    reason: str = Field(min_length=3)
    days: int = Field(default=30, ge=1, le=365)
    export_format: str = Field(default="json")
    preset: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    actor_ref: str | None = None
    issue_type_id: str | None = None
    route: str | None = None
    conversation_id: str | None = None
    model: str | None = None
    has_feedback: bool | None = None
    handoff: bool | None = None
    rating: str | None = None
    feedback_reason: str | None = None
    resolved_status: str | None = None
    idempotency_key: str | None = None
    channel_scope: str | None = None
    query: str | None = None
    source: str | None = None


class FaqCreateRequest(BaseModel):
    faq_key: str
    question: str
    answer: str
    category: str
    keywords: tuple[str, ...]
    owner_unit_id: str
    business_contact: str
    issue_type_ids: tuple[str, ...]
    audience_type: Literal["ALL", "GROUPS"]
    audience_group_ids: tuple[str, ...] = ()
    related_document_ids: tuple[str, ...] = ()
    effective_at: datetime | None = None
    review_due_at: datetime | None = None

    def to_content(self) -> FaqContent:
        return FaqContent.model_validate(
            self.model_dump(exclude={"expected_etag"})
        )


class FaqEditRequest(FaqCreateRequest):
    expected_etag: int = Field(ge=1)


class FaqTestCreateRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    kind: Literal["POSITIVE", "NEGATIVE"]
    utterance: str = Field(min_length=1)
    expected_audience_group_ids: tuple[str, ...] = ()
    source_type: Literal["MANUAL", "CONVERSATION"] = "MANUAL"
    source_correlation_id: str | None = None


class FaqTransitionRequest(BaseModel):
    expected_etag: int = Field(ge=1)


class FaqReviewRequest(FaqTransitionRequest):
    approve: bool
    reason: str = Field(min_length=1)


class FaqReasonRequest(FaqTransitionRequest):
    reason: str = Field(min_length=1)


class ExampleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    expected_issue_type_id: str
    expected_route: Literal["FAQ", "KNOWLEDGE", "TICKET", "HANDOFF"]
    label: Literal["POSITIVE", "NEGATIVE"]
    reason: str | None = None
    source_correlation_id: str | None = None


class ExampleUpdateRequest(ExampleCreateRequest):
    expected_etag: int = Field(ge=1)


class ExampleReviewRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    approve: bool
    reason: str = Field(min_length=1)
    dataset_version: str | None = None


class ExampleRetireRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    reason: str = Field(min_length=1)


class QualityCandidateRefreshRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class QualityCandidateMergeRequest(BaseModel):
    candidate_ids: tuple[str, ...] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    assignee_id: str | None = None
    target_due_at: datetime | None = None


class QualityCaseUpdateRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    assignee_id: str | None = None
    target_due_at: datetime | None = None


class QualityCaseTransitionRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    status: Literal[
        "TRIAGED", "IN_PROGRESS", "WAITING_REVIEW", "OBSERVING",
        "RESOLVED", "WONT_FIX", "DUPLICATE",
    ]
    reason: str | None = None
    resolution_type: str | None = None


class QualityContentLinkRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    faq_id: str | None = None
    document_id: str | None = None


class QualityFaqDraftRequest(BaseModel):
    expected_case_etag: int = Field(ge=1)
    faq_key: str
    question: str
    answer: str
    category: str
    keywords: tuple[str, ...]
    business_contact: str
    audience_type: Literal["ALL", "GROUPS"]
    audience_group_ids: tuple[str, ...] = ()
    related_document_ids: tuple[str, ...] = ()
    effective_at: datetime | None = None
    review_due_at: datetime | None = None


class QualityDocumentDraftRequest(BaseModel):
    expected_case_etag: int = Field(ge=1)
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    markdown_content: str | None = None
    business_contact: str | None = None


class QuestionClusterCorrectionRequest(BaseModel):
    cluster_ids: tuple[str, ...] = Field(min_length=1)
    action: Literal["RENAME", "ACCEPT", "REJECT", "MERGE", "SPLIT"]
    name: str | None = None
    candidate_groups: tuple[tuple[str, ...], ...] = ()


class SyncJobCreateRequest(BaseModel):
    scope_type: Literal["ALL", "FAQ", "DOCUMENT", "FAILED"]
    scope_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=3)


class SyncJobActionRequest(BaseModel):
    reason: str = Field(min_length=3)
    expected_etag: int | None = Field(default=None, ge=1)


class BudgetPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["PERSONAL", "SERVICE", "TEAM", "TENANT", "GLOBAL", "MODEL"]
    scope_id: str = Field(min_length=1)
    period: Literal["DAILY", "MONTHLY"]
    measure: Literal["TWD", "USD", "TOKEN", "LLM_CALL_COUNT"]
    warning_threshold: float = Field(gt=0)
    critical_threshold: float = Field(gt=0)
    owner_unit_id: str = Field(min_length=1)
    notification_target_ids: tuple[str, ...]


class BudgetPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_etag: int = Field(ge=1)
    warning_threshold: float = Field(gt=0)
    critical_threshold: float = Field(gt=0)
    notification_target_ids: tuple[str, ...]


class BudgetPolicyStateRequest(BaseModel):
    expected_etag: int = Field(ge=1)
    enabled: bool
    reason: str = Field(min_length=3)


class PromptCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_prompt_version: str
    dataset_version: str
    taxonomy_version: str
    data_range_start: datetime
    data_range_end: datetime
    masking_policy_version: str


