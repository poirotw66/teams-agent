"""Persisted Portal domain records for documents, reviews, releases, and audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .models_types import (
    AudienceType,
    DocumentLifecycleStatus,
    ParsePreview,
    PortalRole,
    ReleasePurpose,
    ReleaseStatus,
    ReviewDecision,
    StrictModel,
    TestResultStatus,
    ValidationSummary,
    VersionLifecycleStatus,
)


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
    source_aliases: list[str] = Field(default_factory=list)
    current_published_version_id: str | None = None
    draft_version_id: str | None = None
    status: DocumentLifecycleStatus = "DRAFT"
    format: str | None = None
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
    source_type: Literal["MARKDOWN_PASTE", "MARKDOWN_UPLOAD", "PDF", "DOCX"] = "MARKDOWN_PASTE"
    content_hash: str
    canonical_content: str
    change_summary: str = ""
    change_reason: str = ""
    effective_at: str
    review_due_at: str
    audience_type: AudienceType = "ALL_EMPLOYEES"
    audience_group_ids: list[str] = Field(default_factory=list)
    source_aliases: list[str] = Field(default_factory=list)
    content_state: Literal["ACTIVE", "TEST", "PLACEHOLDER", "RETIRED"] = "ACTIVE"
    expires_at: str | None = None
    applicable_environments: list[str] = Field(default_factory=list)
    owner_unit_id: str
    business_contact: str = ""
    category: str = ""
    summary: str = ""
    title: str
    status: VersionLifecycleStatus = "DRAFT"
    asset_slug: str = ""
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    parse_preview: ParsePreview | None = None
    original_asset_name: str | None = None
    original_asset_sha256: str | None = None
    original_asset_content_type: str | None = None
    original_asset_size: int | None = None
    original_artifact_ref: str | None = None
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
    version_number: int | None = None
    title: str
    content_hash: str
    # The release manifest is also the source map consumed by citation
    # previews.  Defaults keep older release manifests readable.
    source_path: str | None = None
    source_type: str = "DERIVED_MARKDOWN"
    original_asset_available: bool = False
    original_asset_name: str | None = None
    artifact_ref: str | None = None
    acl_groups: list[str] | None = None
    source_aliases: list[str] = Field(default_factory=list)
    content_state: Literal["ACTIVE", "TEST", "PLACEHOLDER", "RETIRED"] = "ACTIVE"
    effective_at: str | None = None
    expires_at: str | None = None
    applicable_environments: list[str] = Field(default_factory=list)


class ReleaseRecord(StrictModel):
    release_id: str
    status: ReleaseStatus
    purpose: ReleasePurpose = "UNKNOWN"
    manifest: list[ReleaseManifestEntry] = Field(default_factory=list)
    corpus_hash: str
    target_manifest_hash: str | None = None
    index_artifact_uri: str
    index_setting_version: str
    created_at: datetime
    activated_at: datetime | None = None
    verified_at: datetime | None = None
    previous_release_id: str | None = None
    created_by: str
    approved_by: str | None = None
    failure_summary: str = ""
    tenant_id: str = "default"
    artifact_bucket: str | None = None
    artifact_object_prefix: str | None = None
    manifest_generation: int | None = None
    index_generation: int | None = None
    index_sha256: str | None = None
    chunk_count: int = 0
    vector_count: int = 0
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_backend: str | None = None
    embedding_vertex_location: str | None = None
    file_search_store: str | None = None
    hybrid_backend_ready: bool = False
    file_search_backend_ready: bool = False


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
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IdempotencyRecord(StrictModel):
    key: str
    payload_hash: str
    response: dict[str, Any] | list[Any] | str | None = None
    status: Literal["PROCESSING", "COMPLETED", "FAILED"] = "COMPLETED"
    created_at: datetime
    updated_at: datetime | None = None
