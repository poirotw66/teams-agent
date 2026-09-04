from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_ops_backoffice.api import create_app as create_backoffice_app
from ai_ops_backoffice.settings import BackofficeSettings
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.settings import PortalSettings


@pytest.fixture
def portal_client() -> TestClient:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "require_dual_approval", False)
    object.__setattr__(settings, "delegation_secret", "test-secret")
    object.__setattr__(settings, "require_service_token_with_delegation", False)
    object.__setattr__(settings, "embedding_model", None)
    app = create_portal_app(settings)
    return TestClient(app)


def mgr_headers(user_id: str = "mgr.ops") -> dict[str, str]:
    return {
        "X-Portal-User-Id": user_id,
        "X-Portal-User-Name": "Manager Ops",
        "X-Portal-Role": "MANAGER",
        "X-Portal-Owner-Units": "IT Service Desk",
    }


def make_doc_payload(title: str, body: str = "Test body content") -> dict[str, str]:
    return {
        "title": title,
        "summary": f"Summary for {title}",
        "category": "Testing",
        "owner_unit_id": "IT Service Desk",
        "business_contact": "it@example.test",
        "audience_type": "ALL_EMPLOYEES",
        "audience_group_ids": [],
        "effective_at": "2026-08-01",
        "review_due_at": "2026-12-01",
        "change_summary": "Initial draft",
        "change_reason": f"Creating {title}",
        "markdown_content": f"# {title}\n\n## 正文（canonical）\n\n{body}",
    }


def _create_and_publish(client: TestClient, title: str, body: str = "Body") -> tuple[str, str, str]:
    """Helper: create, submit, approve, and publish a document, returning (doc_id, ver_id, release_id)."""
    headers = mgr_headers()
    # 1. Create
    resp = client.post("/api/documents", json=make_doc_payload(title, body), headers=headers)
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document"]["document_id"]
    ver_id = resp.json()["draft_version"]["version_id"]
    etag = resp.json()["document"]["etag"]

    # 2. Submit review
    sub = client.post(
        f"/api/documents/{doc_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready to publish"},
        headers=headers,
    )
    assert sub.status_code == 200, sub.text
    review_id = sub.json()["open_review"]["review_id"]

    # 3. Approve
    dec = client.post(
        f"/api/reviews/{review_id}/decision",
        json={"decision": "APPROVED", "comment": "Approved for release"},
        headers=headers,
    )
    assert dec.status_code == 200, dec.text

    # 4. Publish
    pub = client.post(
        f"/api/documents/{doc_id}/publish",
        json={"version_id": ver_id, "reason": f"Publishing {title}"},
        headers=headers,
    )
    assert pub.status_code == 200, pub.text
    release_id = pub.json()["release_id"]
    return doc_id, ver_id, release_id


def test_new_release_preserves_document_undergoing_revision(portal_client: TestClient) -> None:
    headers = mgr_headers()

    # 1. Publish Document A as Release 1
    doc_a_id, ver_a_1, rel_1 = _create_and_publish(portal_client, "Doc A", "Doc A Content v1")

    # 2. Start revision on Document A -> Document A status becomes DRAFT
    rev = portal_client.post(
        f"/api/documents/{doc_a_id}/start-revision",
        headers=headers,
    )
    assert rev.status_code == 200, rev.text
    doc_a_detail = rev.json()
    assert doc_a_detail["document"]["status"] == "DRAFT"
    assert doc_a_detail["document"]["current_published_version_id"] == ver_a_1
    assert doc_a_detail["draft_version"]["version_id"] != ver_a_1

    # 3. Publish Document B -> Release 2
    doc_b_id, ver_b_1, rel_2 = _create_and_publish(portal_client, "Doc B", "Doc B Content v1")
    assert rel_2 != rel_1

    # 4. Fetch Release 2 and verify manifest contains BOTH Doc A (v1) and Doc B (v1)
    releases = portal_client.get("/api/releases", headers=headers).json()
    active_release = next(r for r in releases if r["release_id"] == rel_2)
    manifest_map = {item["document_id"]: item["version_id"] for item in active_release["manifest"]}

    assert doc_a_id in manifest_map, "Document A must NOT be dropped from the release while being revised"
    assert manifest_map[doc_a_id] == ver_a_1, "Document A must remain at published version 1 in release"
    assert doc_b_id in manifest_map
    assert manifest_map[doc_b_id] == ver_b_1


def test_rollback_and_subsequent_release_does_not_resurrect_rolled_back_document(
    portal_client: TestClient,
) -> None:
    headers = mgr_headers()

    # 1. Release 1: Doc A
    doc_a_id, _ver_a_1, rel_1 = _create_and_publish(portal_client, "Doc A", "Doc A Content")

    # 2. Release 2: Doc A + Doc B
    doc_b_id, _ver_b_1, _rel_2 = _create_and_publish(portal_client, "Doc B", "Doc B Content")

    # 3. Rollback to Release 1
    rb = portal_client.post(
        "/api/releases/rollback",
        json={"release_id": rel_1, "reason": "Rollback regression in Doc B"},
        headers=headers,
    )
    assert rb.status_code == 200, rb.text

    # 4. Verify Doc B's document status in repository is now UNPUBLISHED and pointer cleared
    doc_b_detail = portal_client.get(f"/api/documents/{doc_b_id}", headers=headers).json()
    assert doc_b_detail["document"]["status"] == "UNPUBLISHED"
    assert doc_b_detail["document"]["current_published_version_id"] is None

    # 5. Publish Document C -> Release 3
    doc_c_id, _ver_c_1, rel_3 = _create_and_publish(portal_client, "Doc C", "Doc C Content")

    # 6. Verify Release 3 manifest contains Doc A and Doc C, but DOES NOT contain rolled-back Doc B
    releases = portal_client.get("/api/releases", headers=headers).json()
    active_release = next(r for r in releases if r["release_id"] == rel_3)
    manifest_map = {item["document_id"]: item["version_id"] for item in active_release["manifest"]}

    assert doc_a_id in manifest_map
    assert doc_c_id in manifest_map
    assert doc_b_id not in manifest_map, "Rolled-back Doc B must NOT be resurrected into a new release"


def test_idempotency_prevents_duplicate_draft_creation(portal_client: TestClient) -> None:
    headers = {**mgr_headers(), "Idempotency-Key": "idem-key-draft-999"}
    payload = make_doc_payload("Idempotent Doc")

    # Double post with same Idempotency-Key
    resp1 = portal_client.post("/api/documents", json=payload, headers=headers)
    resp2 = portal_client.post("/api/documents", json=payload, headers=headers)

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    doc_id1 = resp1.json()["document"]["document_id"]
    doc_id2 = resp2.json()["document"]["document_id"]
    assert doc_id1 == doc_id2, "Double-post with same Idempotency-Key must return identical document"

    # Verify repository only contains 1 document
    docs = portal_client.get("/api/documents", headers=mgr_headers()).json()["items"]
    assert len(docs) == 1


def test_idempotency_prevents_duplicate_publish_and_rollback(portal_client: TestClient) -> None:
    headers = mgr_headers()

    # Create & approve Doc 1
    create_resp = portal_client.post(
        "/api/documents",
        json=make_doc_payload("Doc 1"),
        headers=headers,
    ).json()
    doc_id = create_resp["document"]["document_id"]
    ver_id = create_resp["draft_version"]["version_id"]
    etag = create_resp["document"]["etag"]

    sub = portal_client.post(
        f"/api/documents/{doc_id}/submit-review",
        json={"etag": etag, "change_reason": "Review request"},
        headers=headers,
    )
    review_id = sub.json()["open_review"]["review_id"]
    dec = portal_client.post(
        f"/api/reviews/{review_id}/decision",
        json={"decision": "APPROVED", "comment": "Approved for release"},
        headers=headers,
    )
    assert dec.status_code == 200, dec.text

    # Double publish with same Idempotency-Key
    pub_headers = {**headers, "Idempotency-Key": "pub-key-888"}
    pub1 = portal_client.post(
        f"/api/documents/{doc_id}/publish",
        json={"version_id": ver_id, "reason": "First publish"},
        headers=pub_headers,
    )
    pub2 = portal_client.post(
        f"/api/documents/{doc_id}/publish",
        json={"version_id": ver_id, "reason": "First publish"},
        headers=pub_headers,
    )
    assert pub1.status_code == 200
    assert pub2.status_code == 200
    assert pub1.json()["release_id"] == pub2.json()["release_id"]

    # Different payload with same key returns 409 Conflict
    pub_conflict = portal_client.post(
        f"/api/documents/{doc_id}/publish",
        json={"version_id": ver_id, "reason": "First publish different payload"},
        headers=pub_headers,
    )
    assert pub_conflict.status_code == 409

    # Verify only 1 release was created
    releases = portal_client.get("/api/releases", headers=headers).json()
    assert len(releases) == 1
    rel1_id = releases[0]["release_id"]

    # Create & publish Doc 2 to have Release 2
    _create_and_publish(portal_client, "Doc 2")
    releases = portal_client.get("/api/releases", headers=headers).json()
    assert len(releases) == 2

    # Double rollback to Rel 1 with same Idempotency-Key
    rb_headers = {**headers, "Idempotency-Key": "rb-key-777"}
    rb1 = portal_client.post(
        "/api/releases/rollback",
        json={"release_id": rel1_id, "reason": "Rollback duplicate test"},
        headers=rb_headers,
    )
    rb2 = portal_client.post(
        "/api/releases/rollback",
        json={"release_id": rel1_id, "reason": "Rollback duplicate test"},
        headers=rb_headers,
    )
    assert rb1.status_code == 200
    assert rb2.status_code == 200
    assert rb1.json()["release_id"] == rb2.json()["release_id"]


def test_bff_proxy_forwards_idempotency_key(portal_client: TestClient) -> None:
    from httpx import ASGITransport

    portal_app = portal_client.app
    transport = ASGITransport(app=portal_app)

    settings = BackofficeSettings.from_env()
    object.__setattr__(settings, "knowledge_bridge_enabled", True)
    object.__setattr__(settings, "knowledge_delegation_secret", "test-secret")
    object.__setattr__(settings, "knowledge_internal_url", "http://knowledge-portal-internal:8090")

    backoffice_app = create_backoffice_app(settings=settings, knowledge_transport=transport)
    bo_client = TestClient(backoffice_app)

    bo_headers = {
        "X-Backoffice-User-Id": "admin.bff",
        "X-Backoffice-User-Name": "Admin BFF",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "Idempotency-Key": "bff-idem-42",
    }
    payload = make_doc_payload("BFF Idempotent Doc")

    resp1 = bo_client.post("/api/knowledge/documents", json=payload, headers=bo_headers)
    resp2 = bo_client.post("/api/knowledge/documents", json=payload, headers=bo_headers)

    assert resp1.status_code == 200, resp1.text
    assert resp2.status_code == 200, resp2.text

    doc_id1 = resp1.json()["document"]["document_id"]
    doc_id2 = resp2.json()["document"]["document_id"]
    assert doc_id1 == doc_id2, "BFF proxy must forward Idempotency-Key so duplicate request returns same document"
