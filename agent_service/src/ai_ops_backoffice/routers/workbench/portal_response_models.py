"""Portal-proxied workbench DTO shapes for OpenAPI → TS codegen.

These names match console_frontend workbench/types so generated schemas can
replace handwritten duplicates.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .response_models import ChunkingProfile, ChunkQualityIssue, ChunkQualitySummary, IngestionStage


class PortalImportAsset(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    filename: str
    content_base64: str


class PortalImportResult(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    mode: Literal["sync", "async"] | None = None
    jobId: str | None = None
    status: str | None = None
    result: PortalImportResult | None = None
    title: str | None = None
    owner_unit_id: str | None = None
    effective_at: str | None = None
    review_due_at: str | None = None
    audience_type: Literal["ALL_EMPLOYEES", "RESTRICTED_GROUPS"] | None = None
    audience_group_ids: list[str] | None = None
    markdown_content: str | None = None
    assets: list[PortalImportAsset] | None = None
    original_asset_token: str | None = None
    source_type: Literal["PDF", "DOCX", "MARKDOWN_UPLOAD"] | None = None
    page_count: int | None = None
    byteSize: int | None = None
    stage: IngestionStage | None = None
    error: str | None = None
    warnings: list[str] | None = None


class PortalDocumentRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    document_id: str
    title: str
    category: str
    status: str
    etag: str | None = None
    updated_at: str
    updated_by: str
    format: str | None = None


class PortalDocumentList(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    items: list[PortalDocumentRecord]


class PortalDocumentVersionSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    version_id: str
    version_number: int
    original_asset_name: str | None = None
    original_asset_size: int | None = None


class PortalDocumentDetail(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    document: PortalDocumentRecord
    draft_version: PortalDocumentVersionSummary | None = None
    published_version: PortalDocumentVersionSummary | None = None


class PendingPortalReviewItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    review_id: str
    document_id: str


class PendingPortalReviewList(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    items: list[PendingPortalReviewItem]


class ChunkPreviewImageDto(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    path: str
    filename: str
    alt_text: str
    content_type: str
    url: str


class ChunkPreviewChunk(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    parentId: str
    neighborIds: list[str]
    title: str
    content: str
    contentPreview: str
    tokenCount: int
    pageStart: int
    pageEnd: int
    headingPath: list[str]
    contentHash: str
    parserVersion: str
    chunkerVersion: str
    qualityIssues: list[ChunkQualityIssue] | None = None
    images: list[ChunkPreviewImageDto] | None = None


class ChunkPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    documentId: str
    versionId: str
    releaseId: str | None = None
    profile: ChunkingProfile | None = None
    quality: ChunkQualitySummary
    chunks: list[ChunkPreviewChunk]


class PortalWorkbenchDtoCatalog(BaseModel):
    """Bundle referenced only to force portal DTO schemas into OpenAPI components."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    import_result: PortalImportResult
    document_list: PortalDocumentList
    document_detail: PortalDocumentDetail
    pending_reviews: PendingPortalReviewList
    chunk_preview: ChunkPreviewResponse
    note: str = Field(
        default="OpenAPI catalog only; not a runtime product endpoint.",
    )


PortalImportResult.model_rebuild()
PortalWorkbenchDtoCatalog.model_rebuild()
