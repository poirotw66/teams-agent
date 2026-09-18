"""Compatibility facade for knowledge-release artifact validators."""

from __future__ import annotations

from knowledge_core.artifacts import INDEX_RELATIVE_PATH, MANIFEST_FILENAME
from knowledge_core.release_artifacts import (
    KnowledgeIndexArtifact,
    KnowledgeReleaseValidationError,
    inspect_index_artifact,
    validate_release_artifacts,
)

__all__ = [
    "INDEX_RELATIVE_PATH",
    "MANIFEST_FILENAME",
    "KnowledgeIndexArtifact",
    "KnowledgeReleaseValidationError",
    "inspect_index_artifact",
    "validate_release_artifacts",
]
