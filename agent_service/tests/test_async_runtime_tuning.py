"""Tests for Milestone 4: Async Runtime & Cold-Start Tuning.

Validates that non-blocking thread offloading works correctly for heavy I/O:
- SourceTraceResolver async methods (resolve_source_ref_async, resolve_citation_async, references_for_events_async)
- TaxonomyRepository.load_async
- inspect_index_artifact_async and validate_release_artifacts_async
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_ops_backoffice.services.source_trace import SourceTraceResolver
from knowledge_core.release_artifacts import (
    inspect_index_artifact,
    inspect_index_artifact_async,
    validate_release_artifacts,
    validate_release_artifacts_async,
)
from operations_core.taxonomy import TaxonomyRepository


@pytest.mark.asyncio
async def test_taxonomy_repository_load_async(tmp_path: Path) -> None:
    taxonomy_file = tmp_path / "taxonomy.json"
    content = {
        "taxonomy_version": "2026-09-19",
        "generated_at": "2026-09-19T00:00:00Z",
        "issue_types": [
            {
                "issue_type_id": "account.login",
                "display_name": "Login Issue",
                "description": "User cannot login",
                "owner_unit_id": "auth-team",
                "status": "ACTIVE",
                "taxonomy_version": "2026-09-19",
            }
        ],
    }
    taxonomy_file.write_text(json.dumps(content), encoding="utf-8")

    repo = await TaxonomyRepository.load_async(taxonomy_file)
    assert repo.version == "2026-09-19"
    active = repo.list_active()
    assert len(active) == 1
    assert active[0].issue_type_id == "account.login"
    assert repo.get("account.login") is not None
    assert repo.get("nonexistent") is None


@pytest.mark.asyncio
async def test_source_trace_resolver_async_methods(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()

    resolver = SourceTraceResolver(releases_dir=releases_dir)

    # Empty releases directory lookup returns None safely
    source = await resolver.resolve_source_ref_async("test-ref-123", tenant_id="default")
    assert source is None

    # Citation resolution returns None safely when not found
    citation = {"source_id": "nonexistent"}
    citation_res = await resolver.resolve_citation_async(citation)
    assert citation_res is None

    # Empty events references returns empty list
    refs = await resolver.references_for_events_async([])
    assert refs == []


@pytest.mark.asyncio
async def test_release_artifacts_async_inspection(tmp_path: Path) -> None:
    release_root = tmp_path / "releases"
    release_dir = release_root / "rel-001"
    index_dir = release_dir / "index"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "chunks.json"

    index_payload = {
        "chunks": [
            {
                "chunk_id": "c1",
                "text": "sample text",
                "source_path": "doc1.md",
                "vector": [0.1, 0.2, 0.3],
            }
        ],
        "embeddingModel": "test-model",
    }
    index_file.write_text(json.dumps(index_payload), encoding="utf-8")

    sync_result = inspect_index_artifact(index_file)
    async_result = await inspect_index_artifact_async(index_file)

    assert async_result.chunk_count == 1
    assert async_result.vector_count == 1
    assert async_result.sha256 == sync_result.sha256
    assert async_result.embedding_model == "test-model"
    assert async_result.embedding_dimensions == 3

    manifest_file = release_dir / "manifest.json"
    manifest_payload = {
        "releaseId": "rel-001",
        "index": sync_result.to_manifest_dict(),
    }
    manifest_file.write_text(json.dumps(manifest_payload), encoding="utf-8")

    val_sync = validate_release_artifacts(release_root, "rel-001", require_vectors=False)
    val_async = await validate_release_artifacts_async(release_root, "rel-001", require_vectors=False)
    assert val_async == val_sync
