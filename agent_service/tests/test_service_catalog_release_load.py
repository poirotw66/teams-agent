"""Service catalog release load + draft foothold tests (spec §2.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_service.service_scope_evidence import (
    configure_service_scope_from_release,
    get_service_catalog_audit_meta,
    has_service_scope_evidence,
    reset_service_scope_catalog,
)
from knowledge_portal.models import ReleaseManifestEntry
from knowledge_portal.service_catalog_artifact import (
    SERVICE_CATALOG_DRAFT_RELATIVE_PATH,
    validate_service_catalog_payload,
    write_service_catalog_artifact,
    write_service_catalog_draft,
)


def test_release_catalog_wins_over_static_sandbox_aliases(tmp_path: Path) -> None:
    """When catalog/service_catalog.json is loaded, static aliases must not apply."""
    release_id = "release-catalog-authority"
    releases_root = tmp_path / "releases"
    release_dir = releases_root / release_id
    release_dir.mkdir(parents=True)
    write_service_catalog_artifact(
        release_dir,
        release_id=release_id,
        tenant_id="tenant-a",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-seat",
                version_id="v1",
                title="座位搬遷需求",
                content_hash="hash",
                source_path="sources/doc-seat.md",
                acl_groups=["grp_public"],
                # Deliberately omit static-only aliases such as 電腦聯絡單.
                source_aliases=["座位調度試驗別名"],
            )
        ],
    )
    reset_service_scope_catalog()
    try:
        # Static sandbox fallback would match 電腦聯絡單 before catalog load.
        assert has_service_scope_evidence("電腦聯絡單") is True
        configure_service_scope_from_release(releases_root, release_id)
        meta = get_service_catalog_audit_meta()
        assert meta.get("source") == "catalog/service_catalog.json"
        assert has_service_scope_evidence("座位調度試驗別名") is True
        assert has_service_scope_evidence("電腦聯絡單") is False
        assert has_service_scope_evidence("座位遷移") is False
    finally:
        reset_service_scope_catalog()


def test_configure_service_scope_prefers_catalog_artifact_over_manifest(
    tmp_path: Path,
) -> None:
    release_id = "release-catalog"
    releases_root = tmp_path / "releases"
    release_dir = releases_root / release_id
    release_dir.mkdir(parents=True)
    # Manifest has a weaker/different alias set than the catalog artifact.
    (release_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseId": release_id,
                "documents": [
                    {
                        "document_id": "doc-seat",
                        "title": "座位搬遷需求",
                        "source_aliases": ["座位搬遷"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    write_service_catalog_artifact(
        release_dir,
        release_id=release_id,
        tenant_id="tenant-a",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-seat",
                version_id="v1",
                title="座位搬遷需求",
                content_hash="hash",
                source_path="sources/doc-seat.md",
                acl_groups=["grp_public"],
                source_aliases=["座位調度試驗別名", "座位搬遷"],
            )
        ],
    )
    reset_service_scope_catalog()
    try:
        count = configure_service_scope_from_release(releases_root, release_id)
        assert count >= 1
        assert has_service_scope_evidence("座位調度試驗別名") is True
        meta = get_service_catalog_audit_meta()
        assert meta.get("source") == "catalog/service_catalog.json"
        assert meta.get("schemaVersion") == 1
        assert meta.get("releaseId") == release_id
    finally:
        reset_service_scope_catalog()


def test_invalid_catalog_artifact_falls_back_to_manifest(tmp_path: Path) -> None:
    release_id = "release-bad-catalog"
    releases_root = tmp_path / "releases"
    release_dir = releases_root / release_id
    (release_dir / "catalog").mkdir(parents=True)
    (release_dir / "catalog" / "service_catalog.json").write_text(
        '{"schemaVersion": 0}',
        encoding="utf-8",
    )
    (release_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseId": release_id,
                "documents": [
                    {
                        "document_id": "doc-seat",
                        "title": "座位搬遷需求",
                        "source_aliases": ["座位搬遷"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reset_service_scope_catalog()
    try:
        configure_service_scope_from_release(releases_root, release_id)
        meta = get_service_catalog_audit_meta()
        assert meta.get("source") == "manifest.json"
        assert has_service_scope_evidence("座位搬遷") is True
    finally:
        reset_service_scope_catalog()


def test_write_service_catalog_draft_validates_schema(tmp_path: Path) -> None:
    path = write_service_catalog_draft(
        tmp_path,
        tenant_id="tenant-a",
        services=[
            {
                "serviceId": "seat_relocation",
                "officialName": "座位搬遷需求",
                "aliases": ["座位遷移"],
                "ownerUnitId": "IT Service Desk",
            }
        ],
    )
    assert path.as_posix().endswith(SERVICE_CATALOG_DRAFT_RELATIVE_PATH)
    payload = validate_service_catalog_payload(
        json.loads(path.read_text(encoding="utf-8"))
    )
    assert payload["status"] == "DRAFT"
    assert payload["services"][0]["serviceId"] == "seat_relocation"


def test_validate_service_catalog_rejects_missing_service_id() -> None:
    with pytest.raises(ValueError, match="serviceId"):
        validate_service_catalog_payload(
            {
                "schemaVersion": 1,
                "releaseId": "r1",
                "tenantId": "t1",
                "services": [{"officialName": "X"}],
            }
        )
