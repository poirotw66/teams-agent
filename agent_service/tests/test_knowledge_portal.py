from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowledge_portal.api import create_app
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
        files={"file": ("vpn-guide.pdf", _text_pdf_bytes("VPN login troubleshooting steps"), "application/pdf")},
        headers=portal_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "PDF"
    assert body["page_count"] == 1
    assert "VPN" in body["markdown_content"]


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
            "markdown_content": f'{imported_data["markdown_content"]}\n\n## Updated\n\nUse MFA.',
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
        files={"file": ("vpn-guide.pdf", _text_pdf_bytes("VPN password reset guide"), "application/pdf")},
        headers=portal_headers(user_id="manager.demo", name="Manager Demo", role="MANAGER"),
    )
    assert imported.status_code == 200
    payload = sample_document_payload()
    payload["title"] = imported.json()["title"]
    payload["markdown_content"] = imported.json()["markdown_content"]
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
            "markdown_content": f'{imported.json()["markdown_content"]}\n\n## Updated\n\nVPN v2.',
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
