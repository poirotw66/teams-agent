"""Security and identity checks for the governed ingestion pipeline."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from knowledge_portal.docx_import import docx_to_markdown
from knowledge_portal.file_search_release import (
    load_file_search_release_entries,
)
from knowledge_portal.ingestion_jobs import (
    IngestionStage,
    ensure_ingestion_transition,
)


def _docx_payload() -> bytes:
    output = BytesIO()
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
        "VPN recovery procedure"
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def test_docx_parser_extracts_paragraphs() -> None:
    assert docx_to_markdown(_docx_payload()) == "VPN recovery procedure"


def test_docx_parser_rejects_archive_traversal() -> None:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../word/document.xml", "<document />")

    with pytest.raises(ValueError, match="unsafe member path"):
        docx_to_markdown(output.getvalue())


def test_ingestion_state_machine_rejects_skipping_review() -> None:
    with pytest.raises(ValueError, match="Invalid ingestion transition"):
        ensure_ingestion_transition(
            IngestionStage.PARSING,
            IngestionStage.ACTIVE,
        )


def test_file_search_manifest_requires_explicit_acl_and_identity(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "file-search"
    staging.mkdir()
    (staging / "chk-1.md").write_text("Grounded content", encoding="utf-8")
    (staging / "manifest.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "slug": "chk-1.md",
                        "releaseId": "release-1",
                        "documentId": "doc-1",
                        "versionId": "ver-1",
                        "chunkId": "chk-1",
                        "sourcePath": "sources/doc-1.md",
                        "parentId": "parent-1",
                        "page": 1,
                        "allowedGroups": [],
                        "contentHash": "abc",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no explicit ACL"):
        load_file_search_release_entries(tmp_path)


def test_file_search_manifest_preserves_release_chunk_identity(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "file-search"
    staging.mkdir()
    (staging / "chk-1.md").write_text("Grounded content", encoding="utf-8")
    (staging / "manifest.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "slug": "chk-1.md",
                        "releaseId": "release-1",
                        "documentId": "doc-1",
                        "versionId": "ver-1",
                        "chunkId": "chk-1",
                        "sourcePath": "sources/doc-1.md",
                        "parentId": "parent-1",
                        "page": 1,
                        "allowedGroups": ["grp_public"],
                        "contentHash": "abc",
                        "sourceAliases": ["VPN FAQ"],
                        "contentState": "ACTIVE",
                        "effectiveAt": "2026-01-01",
                        "applicableEnvironments": ["dev"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    entries = load_file_search_release_entries(tmp_path)

    assert entries[0].release_id == "release-1"
    assert entries[0].chunk_id == "chk-1"
    assert entries[0].allowed_groups == ("grp_public",)
    assert entries[0].source_aliases == ("VPN FAQ",)
    assert entries[0].content_state == "ACTIVE"
