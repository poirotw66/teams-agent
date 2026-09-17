from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from agent_service.retrieval import HybridIndex
from knowledge_portal.api import create_app
from knowledge_portal.models import KnowledgeVersionRecord
from knowledge_portal.publisher import ReleasePublisher
from knowledge_portal.settings import PortalSettings


@pytest.fixture
def portal_client() -> TestClient:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    app = create_app(settings)
    return TestClient(app)


def portal_headers(
    *,
    role: str = "CONTRIBUTOR",
    user_id: str = "contributor.demo",
    name: str = "Contributor Demo",
    owner_units: str = "IT Service Desk",
) -> dict[str, str]:
    return {
        "X-Portal-User-Id": user_id,
        "X-Portal-User-Name": name,
        "X-Portal-Role": role,
        "X-Portal-Owner-Units": owner_units,
    }


def sample_document_payload() -> dict[str, str]:
    return {
        "title": "VPN 登入問題",
        "summary": "協助員工排除 VPN 登入失敗。",
        "category": "VPN",
        "owner_unit_id": "IT Service Desk",
        "business_contact": "it-helpdesk@example.test",
        "audience_type": "ALL_EMPLOYEES",
        "audience_group_ids": [],
        "effective_at": "2026-08-01",
        "review_due_at": "2026-12-01",
        "change_summary": "Initial draft",
        "change_reason": "建立新的 VPN 協助文件。",
        "markdown_content": "# VPN 登入問題\n\n## 正文（canonical）\n\n請確認帳號未鎖定。",
    }


def test_create_document_requires_identity_headers(portal_client: TestClient) -> None:
    response = portal_client.post("/api/documents", json=sample_document_payload())
    assert response.status_code == 401


def test_create_and_list_document(portal_client: TestClient) -> None:
    create = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(),
    )
    assert create.status_code == 200
    document_id = create.json()["document"]["document_id"]

    listing = portal_client.get("/api/documents", headers=portal_headers())
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["document_id"] == document_id


def test_versioned_chunk_preview_keeps_page_hierarchy(
    portal_client: TestClient,
) -> None:
    payload = sample_document_payload()
    payload["markdown_content"] = (
        "## Page 1\n# Architecture\n\n"
        "The governed runtime keeps retrieval and authorization together.\n\n"
        "## Page 2\n# Release\n\n"
        "A candidate must pass evaluation before activation."
    )
    created = portal_client.post(
        "/api/documents",
        json=payload,
        headers=portal_headers(),
    )
    document_id = created.json()["document"]["document_id"]

    preview = portal_client.get(
        f"/api/v1/documents/{document_id}/chunk-preview?profile=SLIDE_DECK",
        headers=portal_headers(),
    )

    assert preview.status_code == 200
    assert preview.json()["profile"] == "SLIDE_DECK"
    assert preview.json()["quality"]["coverageRatio"] == 1
    assert [chunk["pageStart"] for chunk in preview.json()["chunks"]] == [1, 2]


def test_chunk_preview_excludes_generated_archive_metadata(
    portal_client: TestClient,
) -> None:
    payload = sample_document_payload()
    payload["markdown_content"] = (
        "---\n"
        "title: Platform guide\n"
        "category: IT Service Guide\n"
        "---\n\n"
        "# Platform guide\n\n"
        "## Archive metadata\n"
        "- **Filename**: `platform.pdf`\n"
        "- **Pages**: 14\n"
        "---\n\n"
        "## Canonical content\n\n"
        + "This governed instruction contains sufficient operational detail. "
        * 30
    )
    created = portal_client.post(
        "/api/documents",
        json=payload,
        headers=portal_headers(),
    )
    document_id = created.json()["document"]["document_id"]

    preview = portal_client.get(
        f"/api/v1/documents/{document_id}/chunk-preview?profile=MANUAL",
        headers=portal_headers(),
    )

    assert preview.status_code == 200
    assert preview.json()["quality"]["acceptable"] is True
    assert all("Archive metadata" not in chunk["content"] for chunk in preview.json()["chunks"])
    assert all("qualityIssues" in chunk for chunk in preview.json()["chunks"])


def test_versioned_chunk_preview_serves_referenced_draft_image(
    portal_client: TestClient,
) -> None:
    payload = sample_document_payload()
    payload["markdown_content"] = "# VPN\n\n![Connection status](assets/p01.png)"
    payload["assets"] = [
        {
            "filename": "p01.png",
            "content_base64": base64.b64encode(b"png-image").decode("ascii"),
        }
    ]
    created = portal_client.post(
        "/api/documents",
        json=payload,
        headers=portal_headers(),
    )
    document_id = created.json()["document"]["document_id"]
    version_id = created.json()["draft_version"]["version_id"]

    preview = portal_client.get(
        f"/api/v1/documents/{document_id}/versions/{version_id}/chunk-preview",
        headers=portal_headers(),
    )

    assert preview.status_code == 200
    image = preview.json()["chunks"][0]["images"][0]
    assert image["filename"] == "p01.png"
    response = portal_client.get(
        image["url"].replace("/api/knowledge/", "/api/", 1),
        headers=portal_headers(),
    )
    assert response.status_code == 200
    assert response.content == b"png-image"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_versioned_asset_rejects_wrong_version(
    portal_client: TestClient,
) -> None:
    created = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(),
    )
    document_id = created.json()["document"]["document_id"]

    response = portal_client.get(
        f"/api/v1/documents/{document_id}/versions/ver-other/assets/p01.png",
        headers=portal_headers(),
    )

    assert response.status_code == 404


def test_validation_blocks_empty_content(portal_client: TestClient) -> None:
    payload = sample_document_payload()
    payload["markdown_content"] = "   "
    response = portal_client.post(
        "/api/documents",
        json=payload,
        headers=portal_headers(),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_bootstrap_release_endpoint(portal_client: TestClient, tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "data_dir", tmp_path)
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn.md").write_text(
        sample_document_payload()["markdown_content"],
        encoding="utf-8",
    )
    client = TestClient(create_app(settings))
    response = client.post(
        "/api/admin/bootstrap-release-0001",
        json={"sources_dir": str(sources), "release_id": "release-0001"},
        headers=portal_headers(role="PLATFORM", user_id="platform.one", name="Platform One"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["release_id"] == "release-0001"
    assert (tmp_path / "releases" / "active_release.json").exists()


def test_draft_search_endpoint(portal_client: TestClient) -> None:
    create = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(),
    )
    document_id = create.json()["document"]["document_id"]
    response = portal_client.post(
        f"/api/documents/{document_id}/draft-search",
        json={"query": "請確認帳號未鎖定", "groups": [], "limit": 4},
        headers=portal_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert "hits" in body
    assert body["matchedDraft"] is True


from pdf_test_helpers import build_text_pdf_bytes


def _text_pdf_bytes(text: str) -> bytes:
    return build_text_pdf_bytes(text)


def test_import_text_pdf(portal_client: TestClient) -> None:
    response = portal_client.post(
        "/api/documents/import-pdf",
        files={
            "file": (
                "vpn-guide.pdf",
                _text_pdf_bytes("VPN login troubleshooting steps"),
                "application/pdf",
            )
        },
        headers=portal_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "PDF"
    assert body["page_count"] == 1
    assert "VPN" in body["markdown_content"]


def test_imported_pdf_original_is_bound_to_version_and_release(tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "data_dir", tmp_path)
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "embedding_model", None)
    client = TestClient(create_app(settings))
    headers = portal_headers(role="MANAGER", user_id="manager.pdf", name="PDF Manager")

    imported = client.post(
        "/api/documents/import-pdf",
        files={
            "file": ("vpn-guide.pdf", _text_pdf_bytes("VPN original source"), "application/pdf")
        },
        headers=headers,
    )
    assert imported.status_code == 200
    import_body = imported.json()
    assert import_body["original_asset_token"].startswith("orig-")
    assert import_body["original_asset_name"] == "vpn-guide.pdf"

    payload = sample_document_payload()
    payload.update(
        {
            "title": import_body["title"],
            "owner_unit_id": import_body["owner_unit_id"],
            "effective_at": import_body["effective_at"],
            "review_due_at": import_body["review_due_at"],
            "markdown_content": import_body["markdown_content"],
            "assets": import_body["assets"],
            "source_type": "PDF",
            "original_asset_token": import_body["original_asset_token"],
        }
    )
    created = client.post("/api/documents", json=payload, headers=headers)
    assert created.status_code == 200
    version = created.json()["draft_version"]
    assert version["original_asset_name"] == "vpn-guide.pdf"
    original_path = (
        tmp_path
        / "portal_originals"
        / "versions"
        / created.json()["document"]["document_id"]
        / version["version_id"]
        / "vpn-guide.pdf"
    )
    assert original_path.read_bytes() == _text_pdf_bytes("VPN original source")

    release = ReleasePublisher(settings).build_release(
        release_id="release-pdf-original",
        published_versions=[KnowledgeVersionRecord.model_validate(version)],
        created_by="manager.pdf",
        previous_release_id=None,
    )
    entry = release.manifest[0]
    assert entry.original_asset_available is True
    assert entry.original_asset_name == "vpn-guide.pdf"
    assert (
        tmp_path
        / "releases"
        / "release-pdf-original"
        / "original"
        / version["document_id"]
        / version["version_id"]
        / "vpn-guide.pdf"
    ).is_file()


def test_release_index_includes_corpus_images(tmp_path: Path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "data_dir", tmp_path)
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "drafts_dir", tmp_path / "portal_drafts")
    object.__setattr__(settings, "embedding_model", None)
    slug = "總公司IP話機操作"
    image_dir = tmp_path / "sources" / "assets" / slug
    image_dir.mkdir(parents=True)
    (image_dir / "p02.png").write_bytes(b"png")
    version = KnowledgeVersionRecord(
        version_id="ver-phone",
        document_id="doc-phone",
        version_number=1,
        content_hash="hash",
        canonical_content=f"取聽筒後按 0。\n\n![話機面板](assets/{slug}/p02.png)\n",
        effective_at="2026-01-01",
        review_due_at="2026-12-31",
        owner_unit_id="IT Service Desk",
        title=slug,
        asset_slug=slug,
        etag="etag-1",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        created_by="author.one",
    )

    ReleasePublisher(settings).build_release(
        release_id="release-corpus-images",
        published_versions=[version],
        created_by="author.one",
        previous_release_id=None,
    )

    index = HybridIndex.load(
        tmp_path / "releases" / "release-corpus-images" / "index" / "chunks.json"
    )
    images = [image for chunk in index.chunks for image in (chunk.images or [])]
    assert [image.path for image in images] == [f"{slug}/p02.png"]
    assert (tmp_path / "releases" / "release-corpus-images" / "assets" / slug / "p02.png").is_file()


def test_release_excludes_ineligible_versions_from_both_backends(
    tmp_path: Path,
) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "data_dir", tmp_path)
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "drafts_dir", tmp_path / "portal_drafts")
    object.__setattr__(settings, "embedding_model", None)
    object.__setattr__(settings, "deployment_environment", "prod")
    created_at = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def version(
        document_id: str,
        *,
        content_state: Literal["ACTIVE", "TEST", "PLACEHOLDER", "RETIRED"],
    ) -> KnowledgeVersionRecord:
        return KnowledgeVersionRecord(
            version_id=f"ver-{document_id}",
            document_id=document_id,
            version_number=1,
            content_hash=f"hash-{document_id}",
            canonical_content=f"# {document_id}\n\nVPN {document_id} instructions.",
            effective_at="2026-01-01",
            review_due_at="2026-12-31",
            owner_unit_id="IT Service Desk",
            title=document_id,
            content_state=content_state,
            applicable_environments=["prod"],
            etag=f"etag-{document_id}",
            created_at=created_at,
            created_by="author.one",
        )

    ReleasePublisher(settings).build_release(
        release_id="release-eligibility",
        published_versions=[
            version("approved", content_state="ACTIVE"),
            version("placeholder", content_state="PLACEHOLDER"),
        ],
        created_by="author.one",
        previous_release_id=None,
    )

    release_dir = tmp_path / "releases" / "release-eligibility"
    index = HybridIndex.load(release_dir / "index" / "chunks.json")
    file_search = json.loads(
        (release_dir / "file-search" / "manifest.json").read_text(encoding="utf-8")
    )

    assert {chunk.document_id for chunk in index.chunks} == {"approved"}
    assert {entry["documentId"] for entry in file_search["documents"]} == {"approved"}


def test_import_scanned_pdf_is_rejected(portal_client: TestClient) -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    response = portal_client.post(
        "/api/documents/import-pdf",
        files={"file": ("scan.pdf", buffer.getvalue(), "application/pdf")},
        headers=portal_headers(),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_markdown_upload_update_publish_and_governed_removal(tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "require_dual_approval", False)
    object.__setattr__(settings, "relaxed_workflow", True)
    client = TestClient(create_app(settings))
    manager_headers = portal_headers(
        user_id="manager.demo",
        name="Manager Demo",
        role="MANAGER",
    )

    imported = client.post(
        "/api/documents/import-markdown",
        files={
            "file": (
                "vpn-guide.md",
                b"# VPN Markdown Guide\n\nUse the managed VPN profile.",
                "text/markdown",
            )
        },
        headers=manager_headers,
    )
    assert imported.status_code == 200
    imported_data = imported.json()
    create_payload = sample_document_payload()
    create_payload.update(
        {
            "title": imported_data["title"],
            "owner_unit_id": imported_data["owner_unit_id"],
            "effective_at": imported_data["effective_at"],
            "review_due_at": imported_data["review_due_at"],
            "audience_type": imported_data["audience_type"],
            "audience_group_ids": imported_data["audience_group_ids"],
            "markdown_content": imported_data["markdown_content"],
            "source_type": "MARKDOWN_UPLOAD",
        }
    )
    created = client.post(
        "/api/documents",
        json=create_payload,
        headers=manager_headers,
    )
    assert created.status_code == 200
    document_id = created.json()["document"]["document_id"]

    update_payload = sample_document_payload()
    update_payload.update(
        {
            "etag": created.json()["document"]["etag"],
            "title": imported_data["title"],
            "markdown_content": f"{imported_data['markdown_content']}\n\n## Updated\n\nUse MFA.",
            "change_summary": "Markdown update",
            "change_reason": "Refresh uploaded Markdown",
        }
    )
    updated = client.put(
        f"/api/documents/{document_id}/draft",
        json=update_payload,
        headers=manager_headers,
    )
    assert updated.status_code == 200
    submitted = client.post(
        f"/api/documents/{document_id}/submit-review",
        json={
            "etag": updated.json()["document"]["etag"],
            "change_reason": "Review Markdown upload",
        },
        headers=manager_headers,
    )
    assert submitted.status_code == 200
    review_id = submitted.json()["open_review"]["review_id"]
    approved = client.post(
        f"/api/reviews/{review_id}/decision",
        json={
            "decision": "APPROVED",
            "comment": "Markdown approved",
            "policy_exceptions": [],
        },
        headers=manager_headers,
    )
    assert approved.status_code == 200
    detail = client.get(
        f"/api/documents/{document_id}",
        headers=manager_headers,
    ).json()
    version_id = detail["draft_version"]["version_id"]
    published = client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_id, "reason": "Publish Markdown"},
        headers=manager_headers,
    )
    assert published.status_code == 200
    published_detail = client.get(
        f"/api/documents/{document_id}",
        headers=manager_headers,
    ).json()
    assert published_detail["published_version"]["source_type"] == "MARKDOWN_UPLOAD"

    unpublished = client.post(
        f"/api/documents/{document_id}/unpublish",
        json={"reason": "Retire Markdown"},
        headers=manager_headers,
    )
    assert unpublished.status_code == 200
    assert unpublished.json()["document"]["status"] == "UNPUBLISHED"
    removed = client.delete(
        f"/api/documents/{document_id}?reason=Governed%20Markdown%20retirement",
        headers=manager_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["status"] == "DISCARDED"


def test_pdf_publish_workflow(portal_client: TestClient, tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "require_dual_approval", False)
    object.__setattr__(settings, "relaxed_workflow", True)
    client = TestClient(create_app(settings))

    imported = client.post(
        "/api/documents/import-pdf",
        files={
            "file": (
                "vpn-guide.pdf",
                _text_pdf_bytes("VPN password reset guide"),
                "application/pdf",
            )
        },
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert imported.status_code == 200
    payload = sample_document_payload()
    payload["title"] = imported.json()["title"]
    payload["markdown_content"] = imported.json()["markdown_content"]
    payload["assets"] = imported.json()["assets"]
    payload["change_reason"] = "Import text PDF"

    create = client.post(
        "/api/documents",
        json={**payload, "source_type": "PDF"},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert create.status_code == 200
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]

    submit = client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready"},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    review_id = submit.json()["open_review"]["review_id"]
    client.post(
        f"/api/reviews/{review_id}/decision",
        json={"decision": "APPROVED", "comment": "ok", "policy_exceptions": []},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    detail = client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER"),
    )
    version_id = detail.json()["draft_version"]["version_id"]
    publish = client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_id, "reason": "Go live"},
        headers=portal_headers(role="MANAGER", user_id="manager.demo", name="Manager Demo"),
    )
    assert publish.status_code == 200
    published_version = client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER"),
    ).json()["published_version"]
    assert published_version["source_type"] == "PDF"

    revision = client.post(
        f"/api/documents/{document_id}/start-revision",
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert revision.status_code == 200
    revised_detail = revision.json()
    assert revised_detail["draft_version"]["version_number"] == 2
    assert revised_detail["draft_version"]["source_type"] == "PDF"

    update_payload = sample_document_payload()
    update_payload.update(
        {
            "etag": revised_detail["document"]["etag"],
            "title": imported.json()["title"],
            "markdown_content": f"{imported.json()['markdown_content']}\n\n## Updated\n\nVPN v2.",
            "change_summary": "PDF revision v2",
            "change_reason": "Refresh PDF guidance",
        }
    )
    updated = client.put(
        f"/api/documents/{document_id}/draft",
        json=update_payload,
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert updated.status_code == 200
    submit_v2 = client.post(
        f"/api/documents/{document_id}/submit-review",
        json={
            "etag": updated.json()["document"]["etag"],
            "change_reason": "Review PDF v2",
        },
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert submit_v2.status_code == 200
    review_v2 = submit_v2.json()["open_review"]["review_id"]
    approved_v2 = client.post(
        f"/api/reviews/{review_v2}/decision",
        json={"decision": "APPROVED", "comment": "PDF v2 approved", "policy_exceptions": []},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert approved_v2.status_code == 200
    approved_detail = client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER"),
    ).json()
    version_v2 = approved_detail["draft_version"]["version_id"]
    republished = client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_v2, "reason": "Publish PDF v2"},
        headers=portal_headers(role="MANAGER", user_id="manager.demo", name="Manager Demo"),
    )
    assert republished.status_code == 200
    final_detail = client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER"),
    ).json()
    assert final_detail["published_version"]["version_number"] == 2
    assert final_detail["published_version"]["source_type"] == "PDF"

    unpublished = client.post(
        f"/api/documents/{document_id}/unpublish",
        json={"reason": "Retire PDF v2"},
        headers=portal_headers(role="MANAGER", user_id="manager.demo", name="Manager Demo"),
    )
    assert unpublished.status_code == 200
    assert unpublished.json()["document"]["status"] == "UNPUBLISHED"
    removed = client.delete(
        f"/api/documents/{document_id}?reason=Governed%20retirement",
        headers=portal_headers(role="MANAGER", user_id="manager.demo", name="Manager Demo"),
    )
    assert removed.status_code == 200
    assert removed.json()["status"] == "DISCARDED"
    listing = client.get("/api/documents", headers=portal_headers(role="MANAGER"))
    assert all(item["document_id"] != document_id for item in listing.json()["items"])


def test_review_publish_workflow(portal_client: TestClient, tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "require_dual_approval", False)
    client = TestClient(create_app(settings))

    create = client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert create.status_code == 200
    body = create.json()
    document_id = body["document"]["document_id"]
    etag = body["document"]["etag"]

    for index in range(3):
        test_case = client.post(
            f"/api/documents/{document_id}/test-cases",
            json={"question": f"VPN 問題 {index}", "simulated_audience": [], "notes": ""},
            headers=portal_headers(user_id="author.one", name="Author One"),
        )
        assert test_case.status_code == 200

    submit = client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready for review"},
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert submit.status_code == 200
    review_id = submit.json()["open_review"]["review_id"]

    approve = client.post(
        f"/api/reviews/{review_id}/decision",
        json={
            "decision": "APPROVED",
            "comment": "Looks good",
            "policy_exceptions": [],
        },
        headers=portal_headers(role="REVIEWER", user_id="reviewer.one", name="Reviewer One"),
    )
    assert approve.status_code == 200

    detail = client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER", user_id="manager.one", name="Manager One"),
    )
    version_id = detail.json()["draft_version"]["version_id"]

    publish = client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_id, "reason": "Go live"},
        headers=portal_headers(role="MANAGER", user_id="manager.one", name="Manager One"),
    )
    assert publish.status_code == 200
    release = publish.json()
    assert release["status"] == "ACTIVE"
    assert (tmp_path / "releases" / release["release_id"] / "manifest.json").exists()
    assert (tmp_path / "releases" / "active_release.json").exists()

    dashboard = client.get(
        "/api/dashboard",
        headers=portal_headers(role="MANAGER", user_id="manager.one", name="Manager One"),
    )
    assert dashboard.json()["active_release_id"] == release["release_id"]


def test_relaxed_workflow_skips_test_case_gate(portal_client: TestClient) -> None:
    create = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert create.status_code == 200
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]

    submit = portal_client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready for review"},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert submit.status_code == 200


def test_relaxed_workflow_allows_self_review(portal_client: TestClient) -> None:
    create = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]

    submit = portal_client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready for review"},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    review_id = submit.json()["open_review"]["review_id"]

    approve = portal_client.post(
        f"/api/reviews/{review_id}/decision",
        json={
            "decision": "APPROVED",
            "comment": "Self approved in relaxed mode",
            "policy_exceptions": [],
        },
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert approve.status_code == 200


def test_strict_workflow_requires_three_test_cases(tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "relaxed_workflow", False)
    client = TestClient(create_app(settings))

    create = client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]

    submit = client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready for review"},
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert submit.status_code == 400
    assert "three test questions" in submit.json()["detail"]["message"]


def test_discard_draft_document(portal_client: TestClient) -> None:
    create = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    document_id = create.json()["document"]["document_id"]

    response = portal_client.delete(
        f"/api/documents/{document_id}",
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "DISCARDED"

    listing = portal_client.get("/api/documents", headers=portal_headers(role="MANAGER"))
    assert all(item["document_id"] != document_id for item in listing.json()["items"])


def test_unpublish_document_rebuilds_release(portal_client: TestClient, tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "require_dual_approval", False)
    client = TestClient(create_app(settings))

    create = client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]

    submit = client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready"},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    review_id = submit.json()["open_review"]["review_id"]
    client.post(
        f"/api/reviews/{review_id}/decision",
        json={"decision": "APPROVED", "comment": "ok", "policy_exceptions": []},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    detail = client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER"),
    )
    version_id = detail.json()["draft_version"]["version_id"]
    publish = client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_id, "reason": "Go live"},
        headers=portal_headers(role="MANAGER", user_id="manager.demo", name="Manager Demo"),
    )
    assert publish.status_code == 200

    unpublish = client.delete(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER", user_id="manager.demo", name="Manager Demo"),
    )
    assert unpublish.status_code == 200
    body = unpublish.json()
    assert body["document"]["status"] == "UNPUBLISHED"


def test_pending_reviews_include_review_context(tmp_path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "demo_mode", False)
    object.__setattr__(settings, "relaxed_workflow", True)
    client = TestClient(create_app(settings))

    contributor_headers = {
        "X-Portal-User-Id": "author.one",
        "X-Portal-User-Name": "Author One",
        "X-Portal-Role": "CONTRIBUTOR",
        "X-Portal-Owner-Units": "IT Service Desk",
    }
    reviewer_headers = {
        "X-Portal-User-Id": "reviewer.one",
        "X-Portal-User-Name": "Reviewer One",
        "X-Portal-Role": "REVIEWER",
        "X-Portal-Owner-Units": "IT Service Desk",
    }

    payload = sample_document_payload()
    payload["change_reason"] = "更新 VPN 登入指引"
    create = client.post(
        "/api/documents",
        json=payload,
        headers=contributor_headers,
    )
    assert create.status_code == 200
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]

    test_case_ids: list[str] = []
    for index in range(3):
        test_case = client.post(
            f"/api/documents/{document_id}/test-cases",
            json={"question": f"VPN 問題 {index}", "simulated_audience": [], "notes": ""},
            headers=contributor_headers,
        )
        assert test_case.status_code == 200
        test_case_ids.append(test_case.json()["test_case_id"])

    for test_case_id in test_case_ids[:2]:
        run = client.post(
            f"/api/documents/{document_id}/test-cases/{test_case_id}/run",
            headers=contributor_headers,
        )
        assert run.status_code == 200

    test_runs_res = client.get(
        f"/api/documents/{document_id}/test-runs",
        headers=contributor_headers,
    )
    assert test_runs_res.status_code == 200
    runs = test_runs_res.json()
    assert len(runs) == 2

    filtered_res = client.get(
        f"/api/documents/{document_id}/test-runs?test_case_id={test_case_ids[0]}",
        headers=contributor_headers,
    )
    assert filtered_res.status_code == 200
    filtered_runs = filtered_res.json()
    assert len(filtered_runs) == 1
    assert filtered_runs[0]["test_case_id"] == test_case_ids[0]

    submit = client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready for review"},
        headers=contributor_headers,
    )
    assert submit.status_code == 200

    pending = client.get("/api/reviews/pending", headers=reviewer_headers)
    assert pending.status_code == 200
    items = pending.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["document_id"] == document_id
    assert item["owner_unit_id"] == "IT Service Desk"
    assert item["change_reason"] == "更新 VPN 登入指引"
    assert item["audience_label"] == "全體員工"
    assert item["audience_changed"] is False
    summary = item["test_summary"]
    assert summary["total"] == 3
    assert summary["executed"] == 2
    assert summary["meets_minimum"] is True
