"""Compatibility facade for private-artifact metadata models."""

from __future__ import annotations

from knowledge_core.artifact_models import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScanStatus,
)

__all__ = [
    "ArtifactKind",
    "ArtifactRecord",
    "ArtifactScanStatus",
]
