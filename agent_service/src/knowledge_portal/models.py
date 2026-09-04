from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    "ROLLED_BACK",
    "RELOAD_FAILED",
]
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


class KnowledgeDocumentRecord(StrictModel):
    document_id: str
    title: str
    summary: str = ""
    category: str = ""
    owner_unit_id: str
    business_contact: str = ""
    classification: str = "internal"
    audience_type: AudienceType = "ALL_EMPLOYEES"
    audience_group_ids: list[str] = Field(default_factory=list)
    current_published_version_id: str | None = None
    draft_version_id: str | None = None
    status: DocumentLifecycleStatus = "DRAFT"
    etag: str
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    tenant_id: str | None = None


class KnowledgeVersionRecord(StrictModel):
    version_id: str
    document_id: str
    version_number: int
    source_type: Literal["MARKDOWN_PASTE", "MARKDOWN_UPLOAD", "PDF"] = "MARKDOWN_PASTE"
    content_hash: str
    canonical_content: str
    change_summary: str = ""
    change_reason: str = ""
    effective_at: str
    review_due_at: str
    audience_type: AudienceType = "ALL_EMPLOYEES"
    audience_group_ids: list[str] = Field(default_factory=list)
    owner_unit_id: str
    business_contact: str = ""
    category: str = ""
    summary: str = ""
    title: str
    status: VersionLifecycleStatus = "DRAFT"
    asset_slug: str = ""
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    parse_preview: ParsePreview | None = None
    etag: str
    created_at: datetime
    created_by: str


class ReviewRecord(StrictModel):
    review_id: str
    version_id: str
    document_id: str
    snapshot_hash: str
    submitted_by: str
    submitted_at: datetime
    reviewer_id: str | None = None
    decision: ReviewDecision | None = None
    comment: str = ""
    decided_at: datetime | None = None
    policy_exceptions: list[str] = Field(default_factory=list)


class TestCaseRecord(StrictModel):
    test_case_id: str
    version_id: str
    question: str
    expected_document_id: str | None = None
    simulated_audience: list[str] = Field(default_factory=list)
    notes: str = ""


class TestRunRecord(StrictModel):
    test_run_id: str
    test_case_id: str
    version_id: str
    status: TestResultStatus
    answer_excerpt: str = ""
    cited_titles: list[str] = Field(default_factory=list)
    failure_reason: str = ""
    executed_at: datetime
    executed_by: str


class ReleaseManifestEntry(StrictModel):
    document_id: str
    version_id: str
    title: str
    content_hash: str


class ReleaseRecord(StrictModel):
    release_id: str
    status: ReleaseStatus
    manifest: list[ReleaseManifestEntry] = Field(default_factory=list)
    corpus_hash: str
    index_artifact_uri: str
    index_setting_version: str
    created_at: datetime
    activated_at: datetime | None = None
    verified_at: datetime | None = None
    previous_release_id: str | None = None
    created_by: str
    approved_by: str | None = None
    failure_summary: str = ""


class AuditEventRecord(StrictModel):
    event_id: str
    actor_id: str
    actor_role: PortalRole
    action: str
    target_type: str
    target_id: str
    correlation_id: str
    reason: str = ""
    result: Literal["SUCCESS", "FAILURE"] = "SUCCESS"
    occurred_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateDocumentRequest(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=128)
    owner_unit_id: str = Field(min_length=1, max_length=128)
    business_contact: str = Field(default="", max_length=256)
    audience_type: AudienceType = "ALL_EMPLOYEES"
    audience_group_ids: list[str] = Field(default_factory=list)
    effective_at: str = Field(min_length=1, max_length=32)
    review_due_at: str = Field(min_length=1, max_length=32)
    change_summary: str = Field(default="", max_length=512)
    change_reason: str = Field(min_length=1, max_length=2000)
    markdown_content: str = Field(min_length=1)
    source_type: Literal["MARKDOWN_PASTE", "MARKDOWN_UPLOAD", "PDF"] = "MARKDOWN_PASTE"

    @field_validator("audience_group_ids")
    @classmethod
    def normalize_group_ids(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class UpdateDraftRequest(StrictModel):
    etag: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=128)
    owner_unit_id: str = Field(min_length=1, max_length=128)
    business_contact: str = Field(default="", max_length=256)
    audience_type: AudienceType = "ALL_EMPLOYEES"
    audience_group_ids: list[str] = Field(default_factory=list)
    effective_at: str = Field(min_length=1, max_length=32)
    review_due_at: str = Field(min_length=1, max_length=32)
    change_summary: str = Field(default="", max_length=512)
    change_reason: str = Field(min_length=1, max_length=2000)
    markdown_content: str = Field(min_length=1)


class SubmitReviewRequest(StrictModel):
    etag: str = Field(min_length=1)
    change_reason: str = Field(min_length=1, max_length=2000)


class ReviewDecisionRequest(StrictModel):
    decision: ReviewDecision
    comment: str = Field(min_length=1, max_length=4000)
    policy_exceptions: list[str] = Field(default_factory=list)


class PublishRequest(StrictModel):
    version_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


class RollbackRequest(StrictModel):
    release_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


class RemoveDocumentRequest(StrictModel):
    reason: str = Field(default="Removed from the knowledge library.", max_length=2000)


class CreateTestCaseRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    simulated_audience: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)


class DraftSearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=1000)
    groups: list[str] = Field(default_factory=list)
    limit: int = Field(default=4, ge=1, le=10)


class BootstrapReleaseRequest(StrictModel):
    sources_dir: str = ""
    release_id: str = "release-0001"


class DraftAssetRecord(StrictModel):
    filename: str
    size_bytes: int
    content_type: str
    sha256: str


class DraftAssetListResponse(StrictModel):
    asset_slug: str
    items: list[DraftAssetRecord]


class AssetRefSuggestion(StrictModel):
    asset_slug: str
    filename: str
    markdown: str


class ImportPdfResponse(StrictModel):
    title: str
    owner_unit_id: str
    effective_at: str
    review_due_at: str
    audience_type: AudienceType
    audience_group_ids: list[str] = Field(default_factory=list)
    markdown_content: str
    asset_slug: str
    page_count: int
    source_type: Literal["PDF"] = "PDF"
    warnings: list[str] = Field(default_factory=list)


class ImportMarkdownResponse(StrictModel):
    title: str
    owner_unit_id: str
    effective_at: str
    review_due_at: str
    audience_type: AudienceType
    audience_group_ids: list[str] = Field(default_factory=list)
    markdown_content: str
    asset_slug: str
    warnings: list[str] = Field(default_factory=list)


class DocumentListResponse(StrictModel):
    items: list[KnowledgeDocumentRecord]
    total: int


class DocumentDetailResponse(StrictModel):
    document: KnowledgeDocumentRecord
    draft_version: KnowledgeVersionRecord | None = None
    published_version: KnowledgeVersionRecord | None = None
    open_review: ReviewRecord | None = None
    draft_assets: DraftAssetListResponse | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    next_action: str | None = None
    status_label: str = ""


class WorkQueueItem(StrictModel):
    label: str
    count: int
    route: str
    filter_status: str | None = None


class PendingReviewTestSummary(StrictModel):
    total: int = 0
    executed: int = 0
    pass_count: int = 0
    needs_review_count: int = 0
    fail_count: int = 0
    meets_minimum: bool = False


class PendingReviewItem(StrictModel):
    review_id: str
    document_id: str
    document_title: str
    submitted_by: str
    submitted_at: datetime
    status_label: str = "待審核"
    owner_unit_id: str = ""
    change_reason: str = ""
    audience_label: str = ""
    audience_changed: bool = False
    test_summary: PendingReviewTestSummary = Field(default_factory=PendingReviewTestSummary)


class PendingReviewListResponse(StrictModel):
    items: list[PendingReviewItem]
    total: int


class RoleCapabilities(StrictModel):
    create_document: bool = False
    import_markdown: bool = False
    list_pending_reviews: bool = False
    decide_review: bool = False
    publish: bool = False
    list_releases: bool = False
    manage_releases: bool = False
    view_audit: bool = False


class ReleaseDocumentChange(StrictModel):
    document_id: str
    title: str
    change_type: Literal["ADDED", "REMOVED", "UPDATED"]
    current_version_id: str | None = None
    target_version_id: str | None = None


class ReleaseCompareResponse(StrictModel):
    current_release_id: str | None
    target_release_id: str
    target_is_older: bool = False
    document_count_delta: int = 0
    changes: list[ReleaseDocumentChange] = Field(default_factory=list)


class DashboardSummary(StrictModel):
    my_drafts: int
    my_changes_requested: int = 0
    pending_review: int
    publish_failed: int
    review_due_soon: int
    active_release_id: str | None
    active_release_activated_at: datetime | None = None
    relaxed_workflow: bool = True
    min_test_cases_for_review: int = 0
    demo_mode: bool = True
    portal_profile: Literal["DEMO", "GOVERNED"] = "DEMO"
    actor_role: str = ""
    home_route: str = "#/work"
    work_queues: list[WorkQueueItem] = Field(default_factory=list)
    visible_nav: list[str] = Field(default_factory=lambda: ["work", "knowledge", "reviews"])
    capabilities: RoleCapabilities = Field(default_factory=RoleCapabilities)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_etag(content_hash: str, version: int = 1) -> str:
    return f'W/"{content_hash}-{version}"'


class PortalErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_STATE = "INVALID_STATE"
    AUDIT_FAILED = "AUDIT_FAILED"
