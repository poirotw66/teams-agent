from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from knowledge_core.source_identity import make_source_ref_id
from teams_agent.settings import AgentSettings
from teams_agent.source_release_preview import (
    citation_source_ref_id,
    resolve_release_citation_preview,
)


def _settings(tmp_path: Path) -> AgentSettings:
    return AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
        asset_gcs_bucket="knowledge-bucket",
        asset_gcs_prefix="knowledge-releases",
    )


def test_citation_source_ref_id_matches_knowledge_core() -> None:
    kwargs = {
        "release_id": "release-94829b57e0e3",
        "document_id": "dazhou",
        "version_id": "v1",
        "chunk_id": "chunk-1",
        "source_path": "sources/大州系統_功能無法點選.md",
    }
    assert citation_source_ref_id(**kwargs) == make_source_ref_id(**kwargs)


def test_resolve_release_citation_preview_matches_chunk(tmp_path: Path) -> None:
    source_ref = make_source_ref_id(
        release_id="release-1",
        document_id="dazhou",
        version_id="v1",
        chunk_id="chunk-1",
        source_path="sources/dazhou.md",
    )
    chunks_blob = MagicMock(size=128)
    chunks_blob.download_as_bytes.return_value = (
        '{"chunks":[{"title":"大州系統","document_id":"dazhou","version_id":"v1",'
        '"chunk_id":"chunk-1","source_path":"sources/dazhou.md",'
        '"content":"Open IE options."}]}'
    ).encode("utf-8")

    iterator = MagicMock()
    iterator.prefixes = ["knowledge-releases/tenants/default/releases/release-1/"]
    bucket = MagicMock()
    bucket.blob.return_value = chunks_blob
    client = MagicMock()
    client.list_blobs.return_value = iterator
    client.bucket.return_value = bucket

    with patch("google.cloud.storage.Client", return_value=client):
        preview = resolve_release_citation_preview(
            _settings(tmp_path),
            source_ref_id=source_ref or "",
            tenant_id="default",
        )

    assert preview is not None
    assert preview.title == "大州系統"
    assert preview.release_id == "release-1"
    assert preview.source_path == "sources/dazhou.md"
    assert "IE" in preview.excerpt
