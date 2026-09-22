"""Reuse unchanged chunk vectors from the previous active release.

Formal publish still rebuilds an immutable release directory, but embedding
API calls are skipped when ``content_hash`` (preferred) or ``chunk_id`` matches
the previous index under a compatible embedding model and chunking fingerprint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from knowledge_core.document_models import DocumentChunk
from knowledge_portal.models import ReleaseRecord
from knowledge_portal.settings import PortalSettings
from knowledge_portal.version_assets import read_release_index_payload

logger = logging.getLogger(__name__)

__all__ = [
    "EmbeddingReuseStats",
    "apply_reused_embeddings",
    "index_setting_fingerprint",
    "load_previous_release_index_payload",
]


@dataclass(frozen=True)
class EmbeddingReuseStats:
    reused: int
    pending: int
    skipped_reason: str | None = None

    @property
    def force_full(self) -> bool:
        return self.skipped_reason is not None


def index_setting_fingerprint(
    *,
    chunk_size: int,
    chunk_overlap: int,
    embedding_model: str | None,
    chunker_version: str = "layout-v1",
    chunking_profile: str = "AUTO",
) -> str:
    """Stable gate string stored on ReleaseRecord.index_setting_version."""
    return (
        f"chunker={chunker_version};profile={chunking_profile};"
        f"chunk={chunk_size};overlap={chunk_overlap};"
        f"embedding={embedding_model or 'bm25-only'}"
    )


def _normalize_embedding_model_id(model_id: str) -> str:
    normalized = model_id.strip()
    if ":" in normalized:
        return normalized.split(":", 1)[1].strip()
    return normalized


def _embedding_models_compatible(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return _normalize_embedding_model_id(left) == _normalize_embedding_model_id(right)


def load_previous_release_index_payload(
    settings: PortalSettings,
    previous_release: ReleaseRecord | None,
) -> dict[str, Any] | None:
    if previous_release is None:
        return None
    try:
        return read_release_index_payload(settings, previous_release)
    except (FileNotFoundError, OSError, TypeError, ValueError, RuntimeError) as error:
        logger.info(
            "Incremental embed: previous index unavailable for %s (%s)",
            previous_release.release_id,
            error,
        )
        return None


def apply_reused_embeddings(
    chunks: list[DocumentChunk],
    *,
    previous_payload: dict[str, Any] | None,
    selected_embedding: str | None,
    previous_release: ReleaseRecord | None,
    new_fingerprint: str,
) -> EmbeddingReuseStats:
    """Copy reusable vectors onto ``chunks``; leave others without vectors."""
    if not selected_embedding:
        return EmbeddingReuseStats(reused=0, pending=len(chunks), skipped_reason="bm25_only")
    if previous_payload is None:
        return EmbeddingReuseStats(
            reused=0,
            pending=len(chunks),
            skipped_reason="previous_index_missing",
        )
    if previous_release is not None:
        previous_fingerprint = str(previous_release.index_setting_version or "").strip()
        if previous_fingerprint and previous_fingerprint != new_fingerprint:
            # Accept legacy fingerprints that only differ by the new prefix fields
            # when embedding model / chunk size / overlap still match.
            if not _legacy_fingerprint_compatible(previous_fingerprint, new_fingerprint):
                return EmbeddingReuseStats(
                    reused=0,
                    pending=len(chunks),
                    skipped_reason="index_setting_mismatch",
                )
    previous_model = previous_payload.get("embeddingModel")
    if not _embedding_models_compatible(
        str(previous_model) if previous_model else None,
        selected_embedding,
    ):
        return EmbeddingReuseStats(
            reused=0,
            pending=len(chunks),
            skipped_reason="embedding_model_mismatch",
        )

    by_hash: dict[str, list[float]] = {}
    by_chunk_id: dict[str, list[float]] = {}
    for raw in previous_payload.get("chunks") or []:
        if not isinstance(raw, dict):
            continue
        vector = raw.get("vector")
        if not isinstance(vector, list) or not vector:
            continue
        typed = [float(value) for value in vector]
        content_hash = str(raw.get("content_hash") or "").strip()
        if content_hash:
            by_hash[content_hash] = typed
        chunk_id = str(raw.get("chunk_id") or "").strip()
        if chunk_id:
            by_chunk_id[chunk_id] = typed

    if not by_hash and not by_chunk_id:
        return EmbeddingReuseStats(
            reused=0,
            pending=len(chunks),
            skipped_reason="previous_vectors_empty",
        )

    reused = 0
    for chunk in chunks:
        if chunk.vector:
            reused += 1
            continue
        content_hash = str(chunk.content_hash or "").strip()
        vector = by_hash.get(content_hash) if content_hash else None
        if vector is None:
            vector = by_chunk_id.get(chunk.chunk_id)
        if vector is None:
            continue
        chunk.vector = list(vector)
        reused += 1

    pending = sum(1 for chunk in chunks if not chunk.vector)
    logger.info(
        "Incremental embed: reused=%s pending=%s previous=%s",
        reused,
        pending,
        previous_release.release_id if previous_release else None,
    )
    return EmbeddingReuseStats(reused=reused, pending=pending)


def _legacy_fingerprint_compatible(previous: str, new: str) -> bool:
    """Allow reuse when upgrading from ``chunk=…;overlap=…;embedding=…`` format."""
    previous_parts = _fingerprint_parts(previous)
    new_parts = _fingerprint_parts(new)
    for key in ("chunk", "overlap", "embedding"):
        if previous_parts.get(key) != new_parts.get(key):
            return False
    return True


def _fingerprint_parts(value: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for item in value.split(";"):
        key, separator, raw = item.partition("=")
        if separator:
            parts[key.strip()] = raw.strip()
    return parts
