"""Vertex production releases must record embedding provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_service.gemini_backend import reset_gemini_backend_for_tests
from knowledge_core.artifacts import INDEX_RELATIVE_PATH
from knowledge_portal.publisher_finalize import (
    ReleaseBuildError,
    _require_vertex_index_provenance,
)


def _write_index(release_dir: Path, payload: dict[str, object]) -> None:
    index_path = release_dir / INDEX_RELATIVE_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload), encoding="utf-8")


def test_vertex_production_rejects_developer_api_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_gemini_backend_for_tests()
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    _write_index(
        tmp_path,
        {
            "embeddingModel": "google_genai:gemini-embedding-2",
            "embeddingBackend": "DEVELOPER_API",
            "embeddingDimensions": 2,
            "chunks": [{"vector": [0.1, 0.2]}],
        },
    )
    with pytest.raises(ReleaseBuildError, match="embeddingBackend=VERTEX_AI"):
        _require_vertex_index_provenance(tmp_path)
    reset_gemini_backend_for_tests()


def test_developer_api_skips_vertex_provenance_gate(tmp_path: Path) -> None:
    reset_gemini_backend_for_tests()
    _write_index(
        tmp_path,
        {
            "embeddingModel": "google_genai:gemini-embedding-2",
            "chunks": [{"vector": [0.1, 0.2]}],
        },
    )
    _require_vertex_index_provenance(tmp_path)
    reset_gemini_backend_for_tests()
