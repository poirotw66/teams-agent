from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from agent_service.operations.masking import MASKING_POLICY_VERSION, mask_text, redact_secrets

FaqLifecycleStatus = Literal[
    "DRAFT",
    "IN_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "ACTIVE",
    "DISABLED",
    "SUPERSEDED",
]
AudienceType = Literal["ALL", "GROUPS"]
TestKind = Literal["POSITIVE", "NEGATIVE"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class FaqContent(StrictModel):
    """Immutable business content carried by one FAQ version."""

    faq_key: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=20000)
    category: str = Field(min_length=1, max_length=120)
    keywords: tuple[str, ...] = Field(min_length=1, max_length=40)
    owner_unit_id: str = Field(min_length=1, max_length=160)
    business_contact: str = Field(min_length=1, max_length=320)
    issue_type_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    audience_type: AudienceType
    audience_group_ids: tuple[str, ...] = ()
    effective_at: datetime | None = None
    review_due_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_audience(self) -> FaqContent:
        groups = tuple(
            dict.fromkeys(group.strip() for group in self.audience_group_ids if group.strip())
        )
        if len(groups) != len(self.audience_group_ids):
            raise ValueError("audience_group_ids must be non-empty and unique")
        if self.audience_type == "ALL" and groups:
            raise ValueError("ALL audience cannot specify audience_group_ids")
        if self.audience_type == "GROUPS" and not groups:
            raise ValueError("GROUPS audience requires audience_group_ids")
        if len(set(self.issue_type_ids)) != len(self.issue_type_ids):
            raise ValueError("issue_type_ids must be unique")
        for value in (*self.keywords, *self.issue_type_ids, *self.audience_group_ids):
            if not value.strip() or value != value.strip():
                raise ValueError("list values must be non-blank and trimmed")
        for value in (self.effective_at, self.review_due_at):
            if value is not None and value.utcoffset() is None:
                raise ValueError("FAQ timestamps require a timezone")
        if self.effective_at and self.review_due_at and self.review_due_at <= self.effective_at:
            raise ValueError("review_due_at must be after effective_at")
        return self


class FaqVersion(StrictModel):
    version_id: str = Field(min_length=1)
    faq_id: str = Field(min_length=1)
    version_number: int = Field(ge=1)
    content: FaqContent
    status: FaqLifecycleStatus = "DRAFT"
    created_by: str = Field(min_length=1)
    created_at: datetime
    submitted_at: datetime | None = None
    submitted_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    disabled_by: str | None = None
    disabled_at: datetime | None = None
    disabled_reason: str | None = None
    self_approval_exception: bool = False
    self_approval_exception_reason: str | None = None

    @field_validator("review_reason", "disabled_reason", "self_approval_exception_reason")
    @classmethod
    def _mask_reason(cls, value: str | None) -> str | None:
        return mask_text(value).text if value else value


class FaqRecord(StrictModel):
    faq_id: str = Field(min_length=1)
    faq_key: str = Field(min_length=1)
    status: FaqLifecycleStatus
    draft_version_id: str | None = None
    published_version_id: str | None = None
    created_by: str = Field(min_length=1)
    created_at: datetime
    updated_by: str = Field(min_length=1)
    updated_at: datetime
    etag: int = Field(ge=1)


class FaqTestCase(StrictModel):
    test_case_id: str = Field(min_length=1)
    faq_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    kind: TestKind
    utterance: str = Field(min_length=1, max_length=4000)
    expected_audience_group_ids: tuple[str, ...] = ()
    expected_match: bool
    source_type: Literal["MANUAL", "CONVERSATION"] = "MANUAL"
    source_correlation_id: str | None = None
    masking_policy_version: str = MASKING_POLICY_VERSION
    created_by: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _mask_new_case(cls, value: Any, info: ValidationInfo) -> Any:
        if info.context and info.context.get("persisted"):
            return value
        if isinstance(value, dict):
            value = dict(value)
            if isinstance(value.get("utterance"), str):
                value["utterance"] = mask_text(value["utterance"]).text
            value["masking_policy_version"] = MASKING_POLICY_VERSION
        return value

    @model_validator(mode="after")
    def _match_follows_kind(self) -> FaqTestCase:
        if self.kind == "POSITIVE" and not self.expected_match:
            raise ValueError("positive test must expect a match")
        if self.kind == "NEGATIVE" and self.expected_match:
            raise ValueError("negative test must expect no match")
        if self.source_type == "CONVERSATION" and not self.source_correlation_id:
            raise ValueError("CONVERSATION test source requires source_correlation_id")
        if self.source_type == "MANUAL" and self.source_correlation_id:
            raise ValueError("MANUAL test source must not contain source_correlation_id")
        if self.source_correlation_id and mask_text(self.source_correlation_id).was_masked:
            raise ValueError("source correlation must be an opaque reference, not sensitive text")
        return self


class FaqAuditEvent(StrictModel):
    audit_id: str
    action: str
    actor_id: str
    actor_role: str
    faq_id: str
    version_id: str | None = None
    reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    occurred_at: datetime
    correlation_id: str | None = None
    target_type: Literal["FAQ"] = "FAQ"
    result: Literal["SUCCESS"] = "SUCCESS"
    retention_policy: str = "faq-effective-plus-three-years-pending-governance"

    @field_validator("reason")
    @classmethod
    def _mask_reason(cls, value: str | None) -> str | None:
        return mask_text(value).text if value else value

    @field_validator("before", "after")
    @classmethod
    def _mask_diff(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return redact_secrets(value) if value is not None else None


class IdempotencyRecord(StrictModel):
    key: str
    action: str
    request_fingerprint: str
    result: dict[str, Any]
    created_at: datetime


class FaqRuntimeSnapshot(StrictModel):
    """The only runtime read model: fixed, already-approved answer text."""

    faq_id: str
    faq_key: str
    version_id: str
    question: str
    answer: str
    category: str
    keywords: tuple[str, ...]
    issue_type_ids: tuple[str, ...]
    audience_type: AudienceType
    audience_group_ids: tuple[str, ...]
    effective_at: datetime | None = None


class FaqState(StrictModel):
    faqs: tuple[FaqRecord, ...] = ()
    versions: tuple[FaqVersion, ...] = ()
    tests: tuple[FaqTestCase, ...] = ()
    audits: tuple[FaqAuditEvent, ...] = ()
    idempotency: tuple[IdempotencyRecord, ...] = ()
    active_pointers: dict[str, str] = Field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(UTC)
