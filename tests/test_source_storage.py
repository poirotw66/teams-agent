"""Tests for immutable release source loading."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import NotFound

from teams_agent.settings import AgentSettings
from teams_agent.source_storage import (
    MAX_SOURCE_DOCUMENT_BYTES,
    SourceDocumentUnavailable,
    fetch_release_source_document,
)


def _settings(tmp_path: Path) -> AgentSettings:
    return AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
        asset_gcs_bucket="knowledge-bucket",
        asset_gcs_prefix="knowledge-releases",
    )


def _blob(value: bytes, *, size: int | None = None) -> MagicMock:
    blob = MagicMock(size=len(value) if size is None else size)
    blob.download_as_bytes.return_value = value
    return blob


def test_fetch_release_source_uses_immutable_tenant_path(tmp_path: Path) -> None:
    blob = _blob(b"# Guide\n")
    bucket = MagicMock()
    bucket.blob.return_value = blob
    client = MagicMock()
    client.bucket.return_value = bucket

    with patch("google.cloud.storage.Client", return_value=client):
        document = fetch_release_source_document(
            _settings(tmp_path),
            release_id="release-123",
            source_path="sources/guides/phone.md",
            tenant_id="default",
        )

    assert document == "# Guide\n"
    bucket.blob.assert_called_once_with(
        "knowledge-releases/tenants/default/releases/release-123/sources/guides/phone.md"
    )


@pytest.mark.parametrize(
    ("release_id", "source_path", "tenant_id"),
    [
        ("../release", "sources/doc.md", "default"),
        ("release-1", "../sources/doc.md", "default"),
        ("release-1", "assets/doc.md", "default"),
        ("release-1", "sources/doc.pdf", "default"),
        ("release-1", "sources/doc.md", "../default"),
    ],
)
def test_fetch_release_source_rejects_untrusted_paths(
    tmp_path: Path,
    release_id: str,
    source_path: str,
    tenant_id: str,
) -> None:
    with pytest.raises(SourceDocumentUnavailable):
        fetch_release_source_document(
            _settings(tmp_path),
            release_id=release_id,
            source_path=source_path,
            tenant_id=tenant_id,
        )


def test_fetch_release_source_rejects_non_utf8(tmp_path: Path) -> None:
    blob = _blob(b"\xff\xfe")
    with patch("google.cloud.storage.Client") as client_type:
        client_type.return_value.bucket.return_value.blob.return_value = blob
        with pytest.raises(SourceDocumentUnavailable, match="UTF-8"):
            fetch_release_source_document(
                _settings(tmp_path),
                release_id="release-1",
                source_path="sources/doc.md",
                tenant_id="default",
            )


def test_fetch_release_source_rejects_oversized_blob(tmp_path: Path) -> None:
    blob = _blob(b"", size=MAX_SOURCE_DOCUMENT_BYTES + 1)
    with patch("google.cloud.storage.Client") as client_type:
        client_type.return_value.bucket.return_value.blob.return_value = blob
        with pytest.raises(SourceDocumentUnavailable, match="size limit"):
            fetch_release_source_document(
                _settings(tmp_path),
                release_id="release-1",
                source_path="sources/doc.md",
                tenant_id="default",
            )


def test_fetch_release_source_translates_missing_blob(tmp_path: Path) -> None:
    blob = _blob(b"")
    blob.download_as_bytes.side_effect = NotFound("missing")
    with patch("google.cloud.storage.Client") as client_type:
        client_type.return_value.bucket.return_value.blob.return_value = blob
        with pytest.raises(SourceDocumentUnavailable, match="not found"):
            fetch_release_source_document(
                _settings(tmp_path),
                release_id="release-1",
                source_path="sources/doc.md",
                tenant_id="default",
            )
