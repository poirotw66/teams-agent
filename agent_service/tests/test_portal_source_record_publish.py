"""Tests for portal SourceRecord persistence on release activation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    assert any(rec.mapping_status == "AVAILABLE" for rec in records)


def test_build_source_records_inherits_restricted_acl(tmp_path: Path) -> None:
    index_path = tmp_path / "chunks_restricted.json"
    index_path.write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "chunk-hr-1",
                        "document_id": "doc-hr-private",
                        "version_id": "ver-1",
                        "source_path": "sources/doc-hr-private.md",
                        "title": "HR Private Guide",
                        "text": "restricted salary info",
                        "allowed_groups": ["hr-private"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    release = ReleaseRecord(
        release_id="release-hr-acl-test",
        status="ACTIVE",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-hr-private",
                version_id="ver-1",
                title="HR Private Guide",
                content_hash="hash-hr",
                source_path="sources/doc-hr-private.md",
                source_type="MARKDOWN_PASTE",
                original_asset_available=False,
            )
        ],
        corpus_hash="corp-hr",
        index_artifact_uri=str(index_path),
        index_setting_version="test",
        created_at="2026-09-15T00:00:00+00:00",
        created_by="tester",
    )

    records = build_source_records_for_release(release, tenant_id="default")
    assert len(records) == 2  # 1 chunk record + 1 document-level record

    chunk_record = next(r for r in records if r.chunk_id == "chunk-hr-1")
    doc_record = next(r for r in records if r.chunk_id is None)

    # Both chunk AND document-level source record MUST inherit hr-private!
    assert list(chunk_record.acl_groups) == ["hr-private"]
    assert list(doc_record.acl_groups) == ["hr-private"], (
        f"Document-level record must inherit chunk ACL, got: {doc_record.acl_groups}"
    )


def test_build_source_records_missing_acl_fails_closed(tmp_path: Path) -> None:
    # Manifest entry without chunks and without explicit ACL
    release = ReleaseRecord(
        release_id="release-missing-acl",
        status="ACTIVE",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-unknown-acl",
                version_id="ver-1",
                title="Unknown Document",
                content_hash="hash-unknown",
                source_path="sources/doc-unknown.md",
            )
        ],
        corpus_hash="corp-unknown",
        index_artifact_uri=str(tmp_path / "nonexistent.json"),
        index_setting_version="test",
        created_at="2026-09-15T00:00:00+00:00",
        created_by="tester",
    )

    records = build_source_records_for_release(release, tenant_id="default")
    assert len(records) == 1
    doc_record = records[0]
    # Missing ACL must fail closed to grp_restricted, NOT grp_public
    assert list(doc_record.acl_groups) == ["grp_restricted"]


def test_build_source_records_loads_chunks_from_gs_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloud inventory republish stores gs:// index URIs; chunk identities must load."""
    from knowledge_portal import source_record_publish as publish_mod

    class _Blob:
        def download_as_bytes(self) -> bytes:
            return json.dumps(
                {
                    "chunks": [
                        {
                            "chunk_id": "chk-gcs-1",
                            "document_id": "doc-gcs-1",
                            "version_id": "ver-1",
                            "source_path": "sources/doc-gcs-1.md",
                            "title": "GCS Doc",
                            "content": "from gcs",
                        }
                    ]
                }
            ).encode("utf-8")

    class _Bucket:
        def blob(self, _name: str) -> _Blob:
            return _Blob()

    class _Client:
        def bucket(self, _name: str) -> _Bucket:
            return _Bucket()

    fake_storage = SimpleNamespace(Client=_Client)
    monkeypatch.setitem(__import__("sys").modules, "google.cloud.storage", fake_storage)
    monkeypatch.setattr(
        publish_mod,
        "_load_chunks_from_gcs",
        lambda uri: publish_mod._load_chunks_payload(
            json.dumps(
                {
                    "chunks": [
                        {
                            "chunk_id": "chk-gcs-1",
                            "document_id": "doc-gcs-1",
                            "version_id": "ver-1",
                            "source_path": "sources/doc-gcs-1.md",
                            "title": "GCS Doc",
                            "content": "from gcs",
                        }
                    ]
                }
            )
        ),
    )

    release = ReleaseRecord(
        release_id="release-gcs-index",
        status="ACTIVE",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-gcs-1",
                version_id="ver-1",
                title="GCS Doc",
                content_hash="hash",
                source_path="sources/doc-gcs-1.md",
                source_type="MARKDOWN_PASTE",
            )
        ],
        corpus_hash="corp",
        index_artifact_uri=(
            "gs://itr-aimasteryhub-lab-knowledge-releases/"
            "knowledge-releases/tenants/default/releases/release-gcs-index/index/chunks.json"
        ),
        index_setting_version="test",
        created_at="2026-09-15T00:00:00+00:00",
        created_by="tester",
    )
    records = build_source_records_for_release(release, tenant_id="default")
    assert any(rec.chunk_id == "chk-gcs-1" for rec in records)
    assert any(rec.excerpt == "from gcs" for rec in records)


def test_publish_aborts_and_marks_failed_if_source_records_fail(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from knowledge_portal.api import create_app as create_portal_app
    from knowledge_portal.settings import PortalSettings

    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "data_dir", tmp_path / "data")
    object.__setattr__(settings, "drafts_dir", tmp_path / "drafts")
    object.__setattr__(settings, "state_path", tmp_path / "portal_state.json")
    object.__setattr__(settings, "require_dual_approval", False)
    object.__setattr__(settings, "embedding_model", None)
    object.__setattr__(settings, "agent_api_url", None)
    app = create_portal_app(settings)
    client = TestClient(app)

    headers = {
        "X-Portal-User-Id": "mgr.ops",
        "X-Portal-User-Name": "Manager Ops",
        "X-Portal-Role": "MANAGER",
        "X-Portal-Owner-Units": "IT Service Desk",
    }
    create_res = client.post(
        "/api/documents",
        headers=headers,
        json={
            "title": "Doc 1",
            "summary": "Summary",
            "category": "IT",
            "owner_unit_id": "IT Service Desk",
            "business_contact": "it@test.com",
            "audience_type": "ALL_EMPLOYEES",
            "audience_group_ids": [],
            "effective_at": "2026-01-01",
            "review_due_at": "2026-12-31",
            "change_summary": "Init",
            "change_reason": "Init",
            "markdown_content": "# Doc 1\n\nContent",
        },
    )
    assert create_res.status_code == 200
    doc_id = create_res.json()["document"]["document_id"]
    ver_id = create_res.json()["draft_version"]["version_id"]
    etag = create_res.json()["document"]["etag"]

    sub_res = client.post(
        f"/api/documents/{doc_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready to publish"},
        headers=headers,
    )
    assert sub_res.status_code == 200
    review_id = sub_res.json()["open_review"]["review_id"]

    appr_res = client.post(
        f"/api/reviews/{review_id}/decision",
        json={"decision": "APPROVED", "comment": "LGTM"},
        headers=headers,
    )
    assert appr_res.status_code == 200

    with patch(
        "knowledge_portal.source_record_publish.persist_release_source_records",
        new=AsyncMock(side_effect=OSError("Firestore quota exceeded")),
    ):
        pub_res = client.post(
            f"/api/documents/{doc_id}/publish",
            json={"version_id": ver_id, "reason": "Deploy"},
            headers=headers,
        )
        assert pub_res.status_code >= 400

    active_res = client.get("/api/releases/active", headers=headers)
    assert active_res.status_code == 404 or active_res.json().get("release") is None

    releases_res = client.get("/api/releases", headers=headers)
    assert releases_res.status_code == 200
    releases = releases_res.json()
    failed_release = next((r for r in releases if r["status"] == "FAILED"), None)
    assert failed_release is not None
    assert "Firestore quota exceeded" in failed_release["failure_summary"]

    # Retry publish without the error - should succeed now!
    retry_res = client.post(
        f"/api/documents/{doc_id}/publish",
        json={"version_id": ver_id, "reason": "Retry after resolving quota"},
        headers=headers,
    )
    assert retry_res.status_code == 200, retry_res.text
    release_data = retry_res.json()
    assert release_data["status"] == "ACTIVE"
    assert release_data["release_id"]

    releases_res2 = client.get("/api/releases", headers=headers)
    assert releases_res2.status_code == 200
    releases2 = releases_res2.json()
    active_release = next((r for r in releases2 if r["status"] == "ACTIVE"), None)
    assert active_release is not None
    assert active_release["release_id"] == release_data["release_id"]



