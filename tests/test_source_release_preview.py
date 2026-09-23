from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from citation_asset_gateway.source_release_preview import (
    citation_source_ref_id,
    resolve_release_citation_preview,
)
from teams_agent.settings import AgentSettings


def _stable_source_ref_id(
    *,
    release_id: str | None,
    document_id: str | None,
    version_id: str | None,
    chunk_id: str | None,
    source_path: str | None,
) -> str | None:
    """Same SHA-256 prefix as knowledge_core.source_identity.make_source_ref_id."""

    if not chunk_id and not source_path:
        return None
    payload = "\x1f".join(
        str(value or "")
        for value in (release_id, document_id, version_id, chunk_id, source_path)
    )
    return f"src-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _settings(tmp_path: Path) -> AgentSettings:
    return AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
        asset_gcs_bucket="knowledge-bucket",
        asset_gcs_prefix="knowledge-releases",
    )


def test_citation_source_ref_id_matches_stable_hash() -> None:
    kwargs = {
        "release_id": "release-94829b57e0e3",
        "document_id": "dazhou",
        "version_id": "v1",
        "chunk_id": "chunk-1",
        "source_path": "sources/大州系統_功能無法點選.md",
    }
    assert citation_source_ref_id(**kwargs) == _stable_source_ref_id(**kwargs)


def test_resolve_release_citation_preview_matches_chunk(tmp_path: Path) -> None:
    source_ref = citation_source_ref_id(
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
    ).encode()

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
