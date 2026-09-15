"""Tests for portal SourceRecord persistence on release activation."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_portal.models import ReleaseManifestEntry, ReleaseRecord
from knowledge_portal.source_record_publish import build_source_records_for_release


def test_build_source_records_for_release_includes_artifact(tmp_path: Path) -> None:
    index_path = tmp_path / "chunks.json"
    index_path.write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "doc-portal-1",
                        "version_id": "ver-1",
                        "source_path": "sources/doc-portal-1.md",
                        "title": "Portal PDF",
                        "text": "hello",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    release = ReleaseRecord(
        release_id="release-portal-test",
        status="ACTIVE",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-portal-1",
                version_id="ver-1",
                title="Portal PDF",
                content_hash="abc",
                source_path="sources/doc-portal-1.md",
                source_type="PDF",
                original_asset_available=True,
                original_asset_name="guide.pdf",
                artifact_ref="art-doc-portal-1-ver-1",
            )
        ],
        corpus_hash="corp",
        index_artifact_uri=str(index_path),
        index_setting_version="test",
        created_at="2026-09-15T00:00:00+00:00",
        created_by="tester",
    )

    records = build_source_records_for_release(release, tenant_id="default")
    assert records
    assert any(rec.artifact_ref == "art-doc-portal-1-ver-1" for rec in records)
    assert all(str(rec.source_ref_id).startswith("src-") for rec in records)
    assert any(rec.mapping_status.value == "AVAILABLE" for rec in records)
