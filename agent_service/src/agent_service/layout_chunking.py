"""Compatibility facade for layout-aware chunking (owned by knowledge_core)."""

from __future__ import annotations

from knowledge_core.chunking_profile import ChunkingProfile
from knowledge_core.layout_chunking import (
    ChunkingLimits,
    ChunkQualityIssue,
    ChunkQualityReport,
    RetrievalChunkDraft,
    chunk_parsed_document,
    chunk_quality_issues,
    detect_profile,
    estimate_tokens,
    has_blocking_chunk_issues,
)

__all__ = [
    "ChunkQualityIssue",
    "ChunkQualityReport",
    "ChunkingLimits",
    "ChunkingProfile",
    "RetrievalChunkDraft",
    "chunk_parsed_document",
    "chunk_quality_issues",
    "detect_profile",
    "estimate_tokens",
    "has_blocking_chunk_issues",
]
