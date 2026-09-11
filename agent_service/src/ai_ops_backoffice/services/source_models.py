"""Domain models and enums for source records, artifacts, and locators.

These models define the contracts for immutable source tracing, artifact storage,
and multi-format document localization as specified in PR-2 (F02, F03, F07, F08, A06).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class MappingStatus(str, Enum):
    """Status of the mapping between a cited index chunk and its original source."""

    AVAILABLE = "AVAILABLE"
    INDEX_PENDING = "INDEX_PENDING"
    ORIGINAL_NOT_PRESERVED = "ORIGINAL_NOT_PRESERVED"
    SOURCE_MISSING = "SOURCE_MISSING"
    MAPPING_UNAVAILABLE = "MAPPING_UNAVAILABLE"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
    EDITED_DERIVATIVE = "EDITED_DERIVATIVE"


from agent_service.artifact_models import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScanStatus,
)
from agent_service.document_authorization import DocumentAccessDecision


class LocatorType(str, Enum):
    """Document format type for citation locators."""

    PDF = "PDF"
    OFFICE_PREVIEW = "OFFICE_PREVIEW"
    SPREADSHEET = "SPREADSHEET"
    MARKDOWN = "MARKDOWN"
    UNSUPPORTED = "UNSUPPORTED"


class SourceLocator(BaseModel):
    """Location information within a document for precise source highlighting and jumps."""

    model_config = ConfigDict(extra="ignore")

    locator_type: LocatorType = LocatorType.UNSUPPORTED
    page_index: int | None = Field(
        default=None,
        description="0-indexed physical page number for pagination systems like PDF.",
    )
    page_label: str | None = Field(
        default=None,
        description="Printed or displayed page label (e.g. 'iii', '12').",
    )
    section_path: str | None = Field(
        default=None,
        description="Document section hierarchy or heading path.",
    )
    paragraph_id: str | None = Field(
        default=None,
        description="Specific paragraph anchor or identifier.",
    )
    bbox: list[float] | None = Field(
        default=None,
        description="Bounding box [x0, y0, x1, y1] for highlight overlay.",
    )
    coordinate_system: str | None = Field(
        default=None,
        description="Coordinate system used by bbox (e.g. 'PDF_POINTS_72DPI').",
    )
    sheet_name: str | None = Field(
        default=None,
        description="Spreadsheet sheet or tab name (e.g. 'Q3 Financials').",
    )
    cell_range: str | None = Field(
        default=None,
        description="Spreadsheet cell range (e.g. 'B2:F15').",
    )
    slide_index: int | None = Field(
        default=None,
        description="Presentation slide index (0-based).",
    )
    parser_version: str | None = Field(
        default=None,
        description="Version identifier of the parser that produced this locator.",
    )
    mapping_confidence: float | None = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for this locator mapping.",
    )
    preview_replica_artifact_ref: str | None = Field(
        default=None,
        description="Reference to a PDF preview replica artifact for DOCX/PPTX.",
    )
    converter_version: str | None = Field(
        default=None,
        description="Software version used to generate the preview replica.",
    )
    degraded_reason: str | None = Field(
        default=None,
        description="Human-readable explanation when precise localization is not available.",
    )


class SourceRecord(BaseModel):
    """Immutable mapping between an index chunk/citation and its source artifact."""

    model_config = ConfigDict(extra="ignore")

    source_ref_id: str
    tenant_id: str
    document_id: str
    version_id: str
    release_id: str
    chunk_id: str | None = None
    artifact_ref: str | None = None
    content_hash: str = ""
    locator_ref: str | None = None
    locator: SourceLocator | None = None
    mapping_status: MappingStatus = MappingStatus.AVAILABLE
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    owner_unit_id: str | None = None
    acl_groups: list[str] = Field(default_factory=list)
    source_type: str = "DERIVED_MARKDOWN"
    title: str | None = None
    source_path: str | None = None
    excerpt: str | None = None
    original_asset_name: str | None = None
    is_archived: bool = False
    is_deleted: bool = False
