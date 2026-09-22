"""Tests for thin ACL packaging into release QA sync artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_portal.acl_artifact import (
    ACL_ARTIFACT_RELATIVE_PATH,
    validate_document_acl_payload,
    write_acl_artifact,
)
from knowledge_portal.models import ReleaseManifestEntry
from knowledge_core.runtime_inventory import (
    build_runtime_artifact_inventory,
    is_qa_sync_relative_path,
)


def _manifest_entry(
    document_id: str,
    *,
    acl_groups: list[str] | None = None,
) -> ReleaseManifestEntry:
    return ReleaseManifestEntry(
        document_id=document_id,
        version_id=f"{document_id}-v1",
        title=document_id,
        content_hash=f"hash-{document_id}",
        source_path=f"sources/{document_id}.md",
        acl_groups=acl_groups,
    )


def test_write_acl_artifact_under_acl_prefix(tmp_path: Path) -> None:
    release_dir = tmp_path / "release-acl"
    release_dir.mkdir()
    path = write_acl_artifact(
        release_dir,
        release_id="release-acl",
        tenant_id="tenant-a",
        manifest=[
            _manifest_entry("doc-a", acl_groups=["grp_public"]),
            _manifest_entry("doc-b", acl_groups=["grp_it", "grp_hr"]),
        ],
    )
    assert path.as_posix().endswith(ACL_ARTIFACT_RELATIVE_PATH)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["releaseId"] == "release-acl"
    assert payload["tenantId"] == "tenant-a"
    assert payload["documents"][0]["aclGroups"] == ["grp_public"]
    assert payload["documents"][1]["aclGroups"] == ["grp_it", "grp_hr"]
    assert is_qa_sync_relative_path(ACL_ARTIFACT_RELATIVE_PATH)


def test_acl_artifact_included_in_runtime_inventory(tmp_path: Path) -> None:
    release_dir = tmp_path / "release-inv"
    release_dir.mkdir()
    (release_dir / "index").mkdir()
    (release_dir / "index" / "chunks.json").write_text("{}", encoding="utf-8")
    write_acl_artifact(
        release_dir,
        release_id="release-inv",
        tenant_id="tenant-a",
        manifest=[_manifest_entry("doc-a", acl_groups=["grp_public"])],
    )
    inventory = build_runtime_artifact_inventory(
        generations={
            "index/chunks.json": 1,
            ACL_ARTIFACT_RELATIVE_PATH: 2,
        },
        release_dir=release_dir,
    )
    paths = {entry.relative_path for entry in inventory}
    assert ACL_ARTIFACT_RELATIVE_PATH in paths


def test_validate_document_acl_rejects_empty_group() -> None:
    with pytest.raises(ValueError, match="aclGroups"):
        validate_document_acl_payload(
            {
                "schemaVersion": 1,
                "releaseId": "r1",
                "tenantId": "t1",
                "documents": [{"documentId": "doc-a", "aclGroups": [" "]}],
            }
        )
