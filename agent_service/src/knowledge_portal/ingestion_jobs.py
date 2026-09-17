"""Typed ingestion lifecycle shared by local and cloud job executors."""

from __future__ import annotations

from enum import StrEnum


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


_TRANSITIONS = {
    IngestionStage.UPLOADED: {
        IngestionStage.SCANNING,
        IngestionStage.CANCELLED,
        IngestionStage.FAILED,
    },
    IngestionStage.SCANNING: {
        IngestionStage.PARSING,
        IngestionStage.CANCELLED,
        IngestionStage.FAILED,
    },
    IngestionStage.PARSING: {
        IngestionStage.CHUNK_REVIEW,
        IngestionStage.CANCELLED,
        IngestionStage.FAILED,
    },
    IngestionStage.CHUNK_REVIEW: {
        IngestionStage.INDEXING,
        IngestionStage.CANCELLED,
        IngestionStage.FAILED,
    },
    IngestionStage.INDEXING: {
        IngestionStage.EVALUATING,
        IngestionStage.FAILED,
    },
    IngestionStage.EVALUATING: {
        IngestionStage.READY,
        IngestionStage.CHUNK_REVIEW,
        IngestionStage.FAILED,
    },
    IngestionStage.READY: {
        IngestionStage.ACTIVE,
        IngestionStage.CHUNK_REVIEW,
        IngestionStage.FAILED,
    },
    IngestionStage.ACTIVE: set(),
    IngestionStage.FAILED: {IngestionStage.SCANNING},
    IngestionStage.CANCELLED: set(),
}


def ensure_ingestion_transition(
    current: IngestionStage,
    target: IngestionStage,
) -> None:
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"Invalid ingestion transition: {current} -> {target}")
