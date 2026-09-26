"""Portal HTTP request and response DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .models_records import KnowledgeDocumentRecord, KnowledgeVersionRecord, ReviewRecord
from .models_types import AudienceType, ReviewDecision, StrictModel


class CreateDocumentAsset(StrictModel):
    filename: str = Field(min_length=1, max_length=256)
    content_base64: str = Field(min_length=1)


class CreateDocumentRequest(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=128)
    owner_unit_id: str = Field(min_length=1, max_length=128)
    business_contact: str = Field(default="", max_length=256)
    audience_type: AudienceType = "ALL_EMPLOYEES"
    audience_group_ids: list[str] = Field(default_factory=list)
    source_aliases: list[str] = Field(default_factory=list)
    content_state: Literal["ACTIVE", "TEST", "PLACEHOLDER", "RETIRED"] = "ACTIVE"
    expires_at: str | None = Field(default=None, max_length=32)
    applicable_environments: list[str] = Field(default_factory=list)
    effective_at: str = Field(min_length=1, max_length=32)
    review_due_at: str = Field(min_length=1, max_length=32)
    change_summary: str = Field(default="", max_length=512)
    change_reason: str = Field(min_length=1, max_length=2000)
    markdown_content: str = Field(min_length=1)
    source_type: Literal["MARKDOWN_PASTE", "MARKDOWN_UPLOAD", "PDF", "DOCX"] = "MARKDOWN_PASTE"
    assets: list[CreateDocumentAsset] = Field(default_factory=list)
    original_asset_token: str | None = None

    @field_validator("audience_group_ids")
    @classmethod
    def normalize_group_ids(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("source_aliases", "applicable_environments")
    @classmethod
    def normalize_governance_values(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class UpdateDraftRequest(StrictModel):
    etag: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=128)
    owner_unit_id: str = Field(min_length=1, max_length=128)
    business_contact: str = Field(default="", max_length=256)
    audience_type: AudienceType = "ALL_EMPLOYEES"
    audience_group_ids: list[str] = Field(default_factory=list)
    source_aliases: list[str] = Field(default_factory=list)
    content_state: Literal["ACTIVE", "TEST", "PLACEHOLDER", "RETIRED"] = "ACTIVE"
    expires_at: str | None = Field(default=None, max_length=32)
    applicable_environments: list[str] = Field(default_factory=list)
    effective_at: str = Field(min_length=1, max_length=32)
    review_due_at: str = Field(min_length=1, max_length=32)
    change_summary: str = Field(default="", max_length=512)
    change_reason: str = Field(min_length=1, max_length=2000)
    markdown_content: str = Field(min_length=1)

    @field_validator("audience_group_ids")
    @classmethod
    def normalize_group_ids(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("source_aliases", "applicable_environments")
    @classmethod
    def normalize_governance_values(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


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


class ChunkPreviewImage(StrictModel):
    path: str
    filename: str
    alt_text: str
    content_type: str
    url: str


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
    conversion_mode: Literal["legacy", "converter"] = "legacy"
    conversion_engine: Literal["legacy_text", "gemini_vision", "unknown"] = "legacy_text"
    conversion_gemini_backend: Literal["DEVELOPER_API", "VERTEX_AI"] | None = None
    assets: list[dict[str, str]] = Field(default_factory=list)
    original_asset_token: str | None = None
    original_asset_name: str | None = None
    original_asset_sha256: str | None = None
    original_asset_content_type: str | None = None
    original_asset_size: int | None = None
    mode: Literal["sync"] = "sync"


class PdfConvertJobAccepted(StrictModel):
    mode: Literal["async"] = "async"
    jobId: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    filename: str
    pageCount: int | None = None
    byteSize: int = 0
    message: str = "PDF conversion queued. Poll job status until COMPLETED."


class PdfConvertJobStatusResponse(StrictModel):
    jobId: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    filename: str
    createdAt: str
    updatedAt: str
    pageCount: int | None = None
    byteSize: int = 0
    mode: str = "converter"
    error: str | None = None
    result: ImportPdfResponse | None = None


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
