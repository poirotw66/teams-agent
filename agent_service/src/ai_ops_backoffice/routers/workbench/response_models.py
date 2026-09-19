"""Pydantic response models for workbench console routes.

Named to match console_frontend shared DTO names so OpenAPI → TS codegen
can replace handwritten duplicates.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChunkQualityIssue(StrEnum):
    SHORT = "SHORT"
    HEADING_ONLY = "HEADING_ONLY"
    DUPLICATE = "DUPLICATE"


class IngestionStage(StrEnum):
    UPLOADED = "UPLOADED"
    SCANNING = "SCANNING"
    PARSING = "PARSING"
    CHUNK_REVIEW = "CHUNK_REVIEW"
    INDEXING = "INDEXING"
    EVALUATING = "EVALUATING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ChunkingProfile(StrEnum):
    AUTO = "AUTO"
    SLIDE_DECK = "SLIDE_DECK"
    MANUAL = "MANUAL"
    POLICY = "POLICY"


class FaqItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    questions: list[str]
    answer: str
    category: str
    is_active: bool
    updated_at: str
    updated_by: str | None = None


class ItTicketItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    ticket_number: str
    title: str
    reporter_name: str
    reporter_dept: str
    reporter_ext: str | None = None
    category: Literal["HARDWARE", "ACCESS", "NETWORK", "SOFTWARE"]
    assigned_team: str
    assigned_agent: str | None = None
    status: Literal["DISPATCHED", "IN_PROGRESS", "RESOLVED", "CANCELLED"]
    conversation_id: str | None = None
    created_at: str
    updated_at: str
    resolution_note: str | None = None


class CitationItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    document_id: str
    document_title: str
    similarity_score: float
    snippet: str
    updated_at: str
    is_stale: bool | None = None
    chunk_id: str | None = None
    source_ref_id: str | None = None
    source_type: str | None = None
    source_path: str | None = None
    section: str | None = None
    url: str | None = None
    original_url: str | None = None
    preview_url: str | None = None
    download_url: str | None = None
    content: str | None = None
    page: int | None = None
    policy_id: str | None = None
    is_policy: bool | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    sender: Literal["user", "bot", "system"]
    content: str
    timestamp: str
    feedback: Literal["positive", "negative"] | None = None
    feedback_comment: str | None = None
    citations: list[CitationItem] | None = None


class ConversationDetail(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    reporter_name: str
    reporter_dept: str
    reporter_ext: str
    started_at: str
    topic_summary: str
    status: Literal["PENDING_REVIEW", "ESCALATED_TICKET", "RESOLVED"]
    root_cause: (
        Literal["OUTDATED_DOC", "MISSING_KNOWLEDGE", "MISUNDERSTOOD", "HARDWARE_TICKET"]
        | None
    ) = None
    messages: list[ChatMessage]
    associated_ticket_id: str | None = None


class DashboardKpiMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    total_inquiries_today: int
    inquiries_trend_percentage: float
    ai_resolution_rate: float
    ai_resolved_count: int
    escalated_ticket_count: int
    satisfaction_rate: float
    negative_feedback_count: int
    urgent_attention_count: int


class SpikeAlertActiveBroadcast(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    message: str
    expires_at: str


class SpikeAlertItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    topic: str
    affected_count: int
    window_minutes: int
    created_at: str
    is_active: bool
    active_broadcast: SpikeAlertActiveBroadcast | None = None


class TopFrequentTopic(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    rank: int
    topic: str
    count: int
    resolution_rate: float


class KnowledgeBlindSpot(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    category: str
    status: Literal["HEALTHY", "NEEDS_UPDATE", "HIGH_DEFECT"]
    description: str
    negative_rate: float


class KnowledgeGapItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    cluster_query: str
    frequency: int
    category: str
    sample_conversations: list[str]
    detected_at: str


class OverviewApiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    kpis: DashboardKpiMetrics
    spikeAlert: SpikeAlertItem | None = None
    topTopics: list[TopFrequentTopic]
    blindSpots: list[KnowledgeBlindSpot]
    gaps: list[KnowledgeGapItem] = Field(default_factory=list)


class ManualChunkImage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    path: str
    filename: str
    alt_text: str
    content_type: str
    url: str


class ChunkQualitySummary(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    acceptable: bool
    coverageRatio: float
    sourceBlocks: int
    coveredBlocks: int
    chunkCount: int
    shortChunkCount: int
    headingOnlyCount: int
    orphanMediaCount: int
    duplicateChunkCount: int


class ManualChunkItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    title: str
    content_preview: str
    content: str | None = None
    character_count: int | None = None
    page_number: int | None = None
    page_end: int | None = None
    token_count: int | None = None
    parent_id: str | None = None
    neighbor_ids: list[str] | None = None
    heading_path: list[str] | None = None
    content_hash: str | None = None
    parser_version: str | None = None
    chunker_version: str | None = None
    quality_issues: list[ChunkQualityIssue] | None = None
    images: list[ManualChunkImage] | None = None
    source_path: str | None = None


class ManualDocumentItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    title: str
    file_name: str
    file_size_bytes: int = 0
    version: str
    version_id: str | None = None
    category: str
    status: Literal[
        "LIVE",
        "DRAFT",
        "PARSING",
        "CHUNK_REVIEW",
        "IN_REVIEW",
        "APPROVED",
        "CHANGES_REQUESTED",
        "PUBLISHING",
        "READY",
        "FAILED",
        "ARCHIVED",
    ]
    chunk_count: int
    updated_at: str
    updated_by: str
    chunks: list[ManualChunkItem] | None = None
    chunking_profile: ChunkingProfile | None = None
    quality: ChunkQualitySummary | None = None
    ingestion_stage: IngestionStage | None = None
    job_id: str | None = None
    ingestion_warnings: list[str] | None = None
