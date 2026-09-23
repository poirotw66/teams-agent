"""Source preview fallback when Firestore SourceRecords are missing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_ops_backoffice.services.source_repository import (
    BoundedSourceCache,
    InMemorySourceRecordRepository,
)
from ai_ops_backoffice.services.source_trace_gcs import materialize_release_preview_artifacts
from ai_ops_backoffice.services.source_trace_resolve import resolve_source_ref
from knowledge_core.source_identity import make_source_ref_id


def test_materialize_release_preview_artifacts_downloads_index(tmp_path: Path) -> None:
    objects: dict[str, bytes] = {
        "knowledge-releases/tenants/default/releases/release-cloud/index/chunks.json": json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "chk-1",
                        "document_id": "doc-1",
                        "version_id": "ver-1",
                        "source_path": "sources/doc-1.md",
                        "title": "Cloud Doc",
                        "content": "preview body",
                    }
                ]
            }
        ).encode("utf-8"),
        "knowledge-releases/tenants/default/releases/release-cloud/manifest.json": json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc-1",
                        "version_id": "ver-1",
                        "title": "Cloud Doc",
                        "source_path": "sources/doc-1.md",
                    }
                ]
            }
        ).encode("utf-8"),
        "knowledge-releases/tenants/default/releases/release-cloud/sources/doc-1.md": (
            b"# Cloud Doc\n\npreview body\n"
        ),
    }

    def storage_reader(release_id: str) -> tuple[str, str] | None:
        assert release_id == "release-cloud"
        return (
            "bucket",
            "knowledge-releases/tenants/default/releases/release-cloud",
        )

    import ai_ops_backoffice.services.source_trace_gcs as gcs_mod

    original = gcs_mod._download_gcs_object

    def fake_download(bucket_name: str, object_name: str, dest: Path) -> bool:
        assert bucket_name == "bucket"
        payload = objects.get(object_name)
        if payload is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return True

    gcs_mod._download_gcs_object = fake_download  # type: ignore[assignment]
    try:
        root = materialize_release_preview_artifacts(
            tmp_path,
            "release-cloud",
            project_id="demo-project",
            storage_reader=storage_reader,
        )
    finally:
        gcs_mod._download_gcs_object = original  # type: ignore[assignment]

    assert root is not None
    assert (root / "index" / "chunks.json").is_file()
    assert (root / "sources" / "doc-1.md").is_file()


def test_resolve_source_ref_uses_materialized_active_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_id = "release-cloud"
    chunk_id = "chk-1"
    source_path = "sources/doc-1.md"
    source_ref = make_source_ref_id(
        release_id=release_id,
        document_id="doc-1",
        version_id="ver-1",
        chunk_id=chunk_id,
        source_path=source_path,
    )
    assert source_ref is not None

    release_root = tmp_path / release_id
    (release_root / "index").mkdir(parents=True)
    (release_root / "index" / "chunks.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": chunk_id,
                        "document_id": "doc-1",
                        "version_id": "ver-1",
                        "source_path": source_path,
                        "title": "Cloud Doc",
                        "content": "preview body",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (release_root / "manifest.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc-1",
                        "version_id": "ver-1",
                        "title": "Cloud Doc",
                        "source_path": source_path,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "ai_ops_backoffice.services.source_trace_resolve.read_firestore_active_release_id",
        lambda **_kwargs: release_id,
    )
    monkeypatch.setattr(
        "ai_ops_backoffice.services.source_trace_resolve.materialize_release_preview_artifacts",
        lambda *_args, **_kwargs: release_root,
    )

    resolved = resolve_source_ref(
        releases_dir=tmp_path,
        release_cache={},
        source_repository=InMemorySourceRecordRepository(),
        cache=BoundedSourceCache(),
        source_ref_id=source_ref,
        tenant_id="default",
        gcp_project_id="demo-project",
    )
    assert resolved is not None
    assert resolved.source_ref_id == source_ref
    assert resolved.title == "Cloud Doc"
    assert resolved.content and "preview body" in resolved.content
