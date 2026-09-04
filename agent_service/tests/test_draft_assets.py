from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from knowledge_portal.api import create_app
from knowledge_portal.draft_assets import slug_from_title
from knowledge_portal.settings import PortalSettings


def portal_headers(
    *,
    role: str = "CONTRIBUTOR",
    user_id: str = "contributor.demo",
    name: str = "Contributor Demo",
) -> dict[str, str]:
    return {
        "X-Portal-User-Id": user_id,
        "X-Portal-User-Name": name,
        "X-Portal-Role": role,
        "X-Portal-Owner-Units": "IT Service Desk",
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


@pytest.fixture
def draft_asset_client(tmp_path) -> TestClient:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "drafts_dir", tmp_path / "portal_drafts")
    object.__setattr__(settings, "data_dir", tmp_path)
    object.__setattr__(settings, "require_dual_approval", False)
    object.__setattr__(settings, "embedding_model", None)
    return TestClient(create_app(settings))


def _create_document(client: TestClient, *, markdown_content: str | None = None) -> str:
    payload = sample_document_payload()
    if markdown_content is not None:
        payload["markdown_content"] = markdown_content
    response = client.post(
        "/api/documents",
        json=payload,
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]["document_id"]


def _update_draft_markdown(client: TestClient, document_id: str, markdown_content: str) -> None:
    detail = client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(user_id="author.one", name="Author One"),
    ).json()
    draft = detail["draft_version"]
    document = detail["document"]
    response = client.put(
        f"/api/documents/{document_id}/draft",
        json={
            "etag": document["etag"],
            "title": document["title"],
            "summary": document.get("summary") or "",
            "category": document.get("category") or "",
            "owner_unit_id": document["owner_unit_id"],
            "business_contact": document.get("business_contact") or "",
            "audience_type": document["audience_type"],
            "audience_group_ids": document.get("audience_group_ids") or [],
            "effective_at": draft["effective_at"],
            "review_due_at": draft["review_due_at"],
            "change_summary": draft.get("change_summary") or "",
            "change_reason": draft.get("change_reason") or "Update draft",
            "markdown_content": markdown_content,
        },
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert response.status_code == 200, response.text


def test_import_markdown_parses_front_matter(draft_asset_client: TestClient) -> None:
    raw = """---
title: VPN Guide
owner: IT Service Desk
effectiveDate: 2026-01-01
reviewDate: 2026-12-31
audience:
  - all-employees
---

# VPN Guide

Body text.
"""
    response = draft_asset_client.post(
        "/api/documents/import-markdown",
        files={"file": ("vpn.md", raw.encode("utf-8"), "text/markdown")},
        headers=portal_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "VPN Guide"
    assert body["owner_unit_id"] == "IT Service Desk"
    assert "Body text." in body["markdown_content"]
    assert body["asset_slug"] == "VPN Guide"


def test_import_markdown_uses_filename_when_title_missing(draft_asset_client: TestClient) -> None:
    raw = """# 總公司 IP 話機操作

請依下列步驟操作。
"""
    response = draft_asset_client.post(
        "/api/documents/import-markdown",
        files={
            "file": (
                "總公司IP話機操作.md",
                raw.encode("utf-8"),
                "text/markdown",
            )
        },
        headers=portal_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "總公司IP話機操作"
    assert body["asset_slug"] == "總公司IP話機操作"


def test_import_markdown_preserves_restricted_audience(draft_asset_client: TestClient) -> None:
    raw = """---
title: HR Policy
owner: IT Service Desk
effectiveDate: 2026-01-01
reviewDate: 2026-12-31
audience:
  - hr-team
  - managers
---

# HR Policy

Restricted body.
"""
    response = draft_asset_client.post(
        "/api/documents/import-markdown",
        files={"file": ("hr.md", raw.encode("utf-8"), "text/markdown")},
        headers=portal_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["audience_type"] == "RESTRICTED_GROUPS"
    assert body["audience_group_ids"] == ["hr-team", "managers"]


def test_upload_and_list_draft_assets(draft_asset_client: TestClient) -> None:
    document_id = _create_document(draft_asset_client)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\x0d\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    upload = draft_asset_client.post(
        f"/api/documents/{document_id}/draft/assets",
        files={"files": ("p01.png", BytesIO(png_bytes), "image/png")},
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert upload.status_code == 200
    items = upload.json()["items"]
    assert len(items) == 1
    assert items[0]["filename"] == "p01.png"

    listing = draft_asset_client.get(
        f"/api/documents/{document_id}/draft/assets",
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert listing.status_code == 200
    assert listing.json()["items"][0]["filename"] == "p01.png"


def test_missing_asset_is_blocking_on_validate(draft_asset_client: TestClient) -> None:
    title = sample_document_payload()["title"]
    asset_slug = slug_from_title(title)
    markdown = f"# {title}\n\n![screenshot](assets/{asset_slug}/p01.png)\n"
    document_id = _create_document(draft_asset_client)
    _update_draft_markdown(draft_asset_client, document_id, markdown)
    validate = draft_asset_client.post(
        f"/api/documents/{document_id}/validate",
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert validate.status_code == 200
    issues = validate.json()["issues"]
    assert any(
        issue["code"] == "MISSING_ASSET" and issue["severity"] == "BLOCKING"
        for issue in issues
    )


def test_publisher_copies_assets_into_release(
    draft_asset_client: TestClient,
    tmp_path,
) -> None:
    title = sample_document_payload()["title"]
    asset_slug = slug_from_title(title)
    document_id = _create_document(draft_asset_client)
    markdown = f"# {title}\n\n![screenshot](assets/{asset_slug}/p01.png)\n"
    _update_draft_markdown(draft_asset_client, document_id, markdown)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\x0d\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    upload = draft_asset_client.post(
        f"/api/documents/{document_id}/draft/assets",
        files={"files": ("p01.png", BytesIO(png_bytes), "image/png")},
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert upload.status_code == 200

    detail = draft_asset_client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    etag = detail.json()["document"]["etag"]

    for index in range(3):
        test_case = draft_asset_client.post(
            f"/api/documents/{document_id}/test-cases",
            json={"question": f"VPN question {index}", "simulated_audience": [], "notes": ""},
            headers=portal_headers(user_id="author.one", name="Author One"),
        )
        assert test_case.status_code == 200

    submit = draft_asset_client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready for review"},
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert submit.status_code == 200
    review_id = submit.json()["open_review"]["review_id"]

    approve = draft_asset_client.post(
        f"/api/reviews/{review_id}/decision",
        json={
            "decision": "APPROVED",
            "comment": "Looks good",
            "policy_exceptions": [],
        },
        headers=portal_headers(role="REVIEWER", user_id="reviewer.one", name="Reviewer One"),
    )
    assert approve.status_code == 200

    detail = draft_asset_client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER", user_id="manager.one", name="Manager One"),
    )
    version_id = detail.json()["draft_version"]["version_id"]

    publish = draft_asset_client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_id, "reason": "Go live"},
        headers=portal_headers(role="MANAGER", user_id="manager.one", name="Manager One"),
    )
    assert publish.status_code == 200
    release_id = publish.json()["release_id"]
    asset_path = tmp_path / "releases" / release_id / "assets" / asset_slug / "p01.png"
    assert asset_path.is_file()


def test_start_revision_copies_legacy_assets(
    draft_asset_client: TestClient,
    tmp_path,
) -> None:
    title = sample_document_payload()["title"]
    asset_slug = slug_from_title(title)
    legacy_dir = tmp_path / "assets" / asset_slug
    legacy_dir.mkdir(parents=True)
    legacy_dir.joinpath("p01.png").write_bytes(b"legacy-image")

    markdown = sample_document_payload()["markdown_content"]
    document_id = _create_document(draft_asset_client, markdown_content=markdown)
    detail = draft_asset_client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    etag = detail.json()["document"]["etag"]

    for index in range(3):
        draft_asset_client.post(
            f"/api/documents/{document_id}/test-cases",
            json={"question": f"VPN question {index}", "simulated_audience": [], "notes": ""},
            headers=portal_headers(user_id="author.one", name="Author One"),
        )

    submit = draft_asset_client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready for review"},
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    review_id = submit.json()["open_review"]["review_id"]
    draft_asset_client.post(
        f"/api/reviews/{review_id}/decision",
        json={
            "decision": "APPROVED",
            "comment": "Looks good",
            "policy_exceptions": [],
        },
        headers=portal_headers(role="REVIEWER", user_id="reviewer.one", name="Reviewer One"),
    )
    detail = draft_asset_client.get(
        f"/api/documents/{document_id}",
        headers=portal_headers(role="MANAGER", user_id="manager.one", name="Manager One"),
    )
    version_id = detail.json()["draft_version"]["version_id"]
    draft_asset_client.post(
        f"/api/documents/{document_id}/publish",
        json={"version_id": version_id, "reason": "Go live"},
        headers=portal_headers(role="MANAGER", user_id="manager.one", name="Manager One"),
    )

    revision = draft_asset_client.post(
        f"/api/documents/{document_id}/start-revision",
        headers=portal_headers(user_id="author.one", name="Author One"),
    )
    assert revision.status_code == 200
    assets = revision.json()["draft_assets"]["items"]
    assert any(item["filename"] == "p01.png" for item in assets)
