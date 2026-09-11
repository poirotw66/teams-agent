from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class ArtifactKind(str, Enum):
    """Classification of an artifact stored in private object storage."""

    ORIGINAL = "ORIGINAL"
    DERIVED_MARKDOWN = "DERIVED_MARKDOWN"
    PREVIEW_PDF = "PREVIEW_PDF"
    SOURCE_MAP = "SOURCE_MAP"
    INDEX = "INDEX"


class ArtifactScanStatus(str, Enum):
    """Malware and safety scan status for uploaded artifacts."""

    CLEAN = "CLEAN"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


class ArtifactRecord(BaseModel):
    """Metadata record for an object in private storage. Storage paths are kept private."""

    model_config = ConfigDict(extra="ignore")

    artifact_id: str
    tenant_id: str
    bucket: str | None = None
    object_key: str
    generation: int | str | None = None
    sha256: str
    mime_type: str = "application/octet-stream"
    size: int = 0
    kind: ArtifactKind = ArtifactKind.ORIGINAL
    scan_status: ArtifactScanStatus = ArtifactScanStatus.CLEAN
    retention_class: str = "STANDARD"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
