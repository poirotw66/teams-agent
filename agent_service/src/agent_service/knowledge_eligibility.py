"""Deterministic generation eligibility for governed knowledge chunks."""

from __future__ import annotations

from datetime import datetime

from knowledge_core.eligibility import (
    ACTIVE_CONTENT_STATE,
    is_generation_metadata_eligible,
)

from .documents import DocumentChunk

__all__ = [
    "ACTIVE_CONTENT_STATE",
    "is_chunk_generation_eligible",
    "is_generation_metadata_eligible",
]


def is_chunk_generation_eligible(
    chunk: DocumentChunk,
    *,
    environment: str,
    evaluated_at: datetime | None = None,
) -> bool:
    """Return whether a caller may consider a chunk for answer generation."""

    return is_generation_metadata_eligible(
        content_state=chunk.content_state,
        effective_at=chunk.effective_at,
        expires_at=chunk.expires_at,
        applicable_environments=chunk.applicable_environments,
        environment=environment,
        evaluated_at=evaluated_at,
    )
