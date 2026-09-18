"""Shared Portal model primitives: actors, validation, and lifecycle literals."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PortalRole = Literal["CONTRIBUTOR", "REVIEWER", "MANAGER", "PLATFORM", "AUDITOR"]
AudienceType = Literal["ALL_EMPLOYEES", "RESTRICTED_GROUPS"]
DocumentLifecycleStatus = Literal[
    "DRAFT",
    "IN_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "PUBLISHING",
    "PUBLISHED",
    "PUBLISH_FAILED",
    "UNPUBLISHED",
    "DISCARDED",
]
VersionLifecycleStatus = Literal[
    "DRAFT",
    "IN_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "PUBLISHING",
    "PUBLISHED",
    "PUBLISH_FAILED",
    "REJECTED",
    "DISCARDED",
]
ReviewDecision = Literal["APPROVED", "CHANGES_REQUESTED", "REJECTED"]
ReleaseStatus = Literal[
    "BUILDING",
    "READY",
    "DEPLOYING",
    "ACTIVE",
    "FAILED",
    "GATE_BLOCKED",
    "ROLLED_BACK",
    "RELOAD_FAILED",
]
ReleasePurpose = Literal["PRODUCTION", "E2E", "SHADOW", "UNKNOWN"]
ValidationSeverity = Literal["BLOCKING", "WARNING", "INFO"]
TestResultStatus = Literal["PASS", "NEEDS_REVIEW", "FAIL"]


class PortalActor(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    role: PortalRole
    owner_unit_ids: list[str] = Field(default_factory=list)
    tenant_id: str | None = None


class ValidationIssue(StrictModel):
    code: str
    severity: ValidationSeverity
    message: str
    field: str | None = None


class ValidationSummary(StrictModel):
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def blocking_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "BLOCKING")

    @property
    def has_blocking(self) -> bool:
        return self.blocking_count > 0


class PreviewSegment(StrictModel):
    heading: str
    excerpt: str
    char_count: int


class ParsePreview(StrictModel):
    title: str
    segments: list[PreviewSegment] = Field(default_factory=list)
    image_count: int = 0
    external_image_urls: list[str] = Field(default_factory=list)


class PortalErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_STATE = "INVALID_STATE"
    AUDIT_FAILED = "AUDIT_FAILED"


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_etag(content_hash: str, version: int = 1) -> str:
    return f'W/"{content_hash}-{version}"'
