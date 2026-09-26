"""Tests for incremental embedding reuse across formal publishes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from knowledge_core.document_models import DocumentChunk
from knowledge_portal.incremental_embeddings import (
    apply_reused_embeddings,
    index_setting_fingerprint,
)
from knowledge_portal.models import ReleaseRecord


def _chunk(
    *,
    chunk_id: str,
    content_hash: str,
    vector: list[float] | None = None,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title="t",
        source_path="sources/a.md",
        content="body",
        content_hash=content_hash,
        vector=vector,
    )


def _release(*, fingerprint: str) -> ReleaseRecord:
    return ReleaseRecord(
        release_id="rel-prev",
        status="ACTIVE",
        corpus_hash="c",
        index_artifact_uri="/tmp/index",
        index_setting_version=fingerprint,
        created_at=datetime.now(timezone.utc),
        created_by="admin",
    )


def test_apply_reused_embeddings_prefers_content_hash() -> None:
    fingerprint = index_setting_fingerprint(
        chunk_size=800,
        chunk_overlap=100,
        embedding_model="google_genai:gemini-embedding-2",
    )
    previous_payload: dict[str, Any] = {
        "embeddingModel": "google_genai:gemini-embedding-2",
        "embeddingBackend": "DEVELOPER_API",
        "embeddingDimensions": 3,
        "chunks": [
            {
                "chunk_id": "chk-old-1",
                "content_hash": "hash-a",
                "vector": [0.1, 0.2, 0.3],
            },
            {
                "chunk_id": "chk-old-2",
                "content_hash": "hash-b",
                "vector": [0.4, 0.5, 0.6],
            },
        ],
    }
    chunks = [
        _chunk(chunk_id="chk-new-1", content_hash="hash-a"),
        _chunk(chunk_id="chk-new-2", content_hash="hash-changed"),
    ]
    stats = apply_reused_embeddings(
        chunks,
        previous_payload=previous_payload,
        selected_embedding="google_genai:gemini-embedding-2",
        previous_release=_release(fingerprint=fingerprint),
        new_fingerprint=fingerprint,
    )
    assert stats.reused == 1
    assert stats.pending == 1
    assert chunks[0].vector == [0.1, 0.2, 0.3]
    assert chunks[1].vector is None


def test_apply_reused_embeddings_falls_back_to_chunk_id() -> None:
    fingerprint = index_setting_fingerprint(
        chunk_size=800,
        chunk_overlap=100,
        embedding_model="gemini-embedding-2",
    )
    previous_payload = {
        "embeddingModel": "gemini-embedding-2",
        "embeddingBackend": "DEVELOPER_API",
        "embeddingDimensions": 2,
        "chunks": [
            {"chunk_id": "chk-stable", "content_hash": "", "vector": [1.0, 2.0]},
        ],
    }
    chunks = [_chunk(chunk_id="chk-stable", content_hash="")]
    stats = apply_reused_embeddings(
        chunks,
        previous_payload=previous_payload,
        selected_embedding="google_genai:gemini-embedding-2",
        previous_release=_release(fingerprint=fingerprint),
        new_fingerprint=fingerprint,
    )
    assert stats.reused == 1
    assert chunks[0].vector == [1.0, 2.0]


def test_apply_reused_embeddings_skips_on_model_mismatch() -> None:
    fingerprint = index_setting_fingerprint(
        chunk_size=800,
        chunk_overlap=100,
        embedding_model="google_genai:gemini-embedding-2",
    )
    previous_payload = {
        "embeddingModel": "openai:text-embedding-3-small",
        "chunks": [
            {"chunk_id": "chk-1", "content_hash": "hash-a", "vector": [1.0]},
        ],
    }
    chunks = [_chunk(chunk_id="chk-1", content_hash="hash-a")]
    stats = apply_reused_embeddings(
        chunks,
        previous_payload=previous_payload,
        selected_embedding="google_genai:gemini-embedding-2",
        previous_release=_release(fingerprint=fingerprint),
        new_fingerprint=fingerprint,
    )
    assert stats.force_full
    assert stats.skipped_reason == "embedding_provenance_mismatch"
    assert chunks[0].vector is None


def test_legacy_fingerprint_still_allows_reuse() -> None:
    new_fingerprint = index_setting_fingerprint(
        chunk_size=800,
        chunk_overlap=100,
        embedding_model="google_genai:gemini-embedding-2",
    )
    legacy = "chunk=800;overlap=100;embedding=google_genai:gemini-embedding-2"
    previous_payload = {
        "embeddingModel": "google_genai:gemini-embedding-2",
        "embeddingBackend": "DEVELOPER_API",
        "embeddingDimensions": 1,
        "chunks": [
            {"chunk_id": "chk-1", "content_hash": "hash-a", "vector": [9.0]},
        ],
    }
    chunks = [_chunk(chunk_id="chk-1", content_hash="hash-a")]
    stats = apply_reused_embeddings(
        chunks,
        previous_payload=previous_payload,
        selected_embedding="google_genai:gemini-embedding-2",
        previous_release=_release(fingerprint=legacy),
        new_fingerprint=new_fingerprint,
    )
    assert stats.reused == 1
    assert chunks[0].vector == [9.0]


def test_fingerprint_includes_backend_and_location() -> None:
    fingerprint = index_setting_fingerprint(
        chunk_size=800,
        chunk_overlap=100,
        embedding_model="google_genai:gemini-embedding-2",
        embedding_backend="VERTEX_AI",
        embedding_vertex_location="us",
        embedding_dimensions=768,
    )
    assert "backend=VERTEX_AI" in fingerprint
    assert "location=us" in fingerprint
    assert "dimensions=768" in fingerprint


def test_apply_reused_embeddings_skips_when_provenance_missing() -> None:
    fingerprint = index_setting_fingerprint(
        chunk_size=800,
        chunk_overlap=100,
        embedding_model="google_genai:gemini-embedding-2",
    )
    previous_payload = {
        "embeddingModel": "google_genai:gemini-embedding-2",
        "chunks": [
            {"chunk_id": "chk-1", "content_hash": "hash-a", "vector": [1.0, 2.0]},
        ],
    }
    chunks = [_chunk(chunk_id="chk-1", content_hash="hash-a")]
    stats = apply_reused_embeddings(
        chunks,
        previous_payload=previous_payload,
        selected_embedding="google_genai:gemini-embedding-2",
        previous_release=_release(fingerprint=fingerprint),
        new_fingerprint=fingerprint,
    )
    assert stats.force_full
    assert stats.skipped_reason == "embedding_provenance_mismatch"
    assert chunks[0].vector is None


def test_hybrid_index_add_embeddings_only_missing() -> None:
    from agent_service.retrieval import HybridIndex

    class Client:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(list(texts))
            return [[float(len(text))] for text in texts]

    chunks = [
        _chunk(chunk_id="a", content_hash="h1", vector=[1.0, 2.0]),
        _chunk(chunk_id="b", content_hash="h2"),
    ]
    index = HybridIndex(chunks, embedding_model=None)
    client = Client()
    index.embedding_client = client
    index.add_embeddings(only_missing=True)
    assert len(client.calls) == 1
    assert len(client.calls[0]) == 1
    assert chunks[0].vector == [1.0, 2.0]
    assert chunks[1].vector == [float(len("t\nbody"))]
