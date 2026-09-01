from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from knowledge_portal.api import create_app
from knowledge_portal.capabilities import compute_allowed_actions, compute_next_action
from knowledge_portal.models import (
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    ReviewRecord,
    ValidationSummary,
)
from knowledge_portal.rbac import ensure_can_publish, ensure_can_review, ensure_can_view_audit
from knowledge_portal.settings import PortalSettings


@pytest.fixture
def portal_headers() -> dict[str, str]:
    def _headers(*, role: str = "MANAGER", user_id: str = "manager.demo") -> dict[str, str]:
        return {
            "X-Portal-User-Id": user_id,
            "X-Portal-User-Name": "Manager Demo",
            "X-Portal-Role": role,
            "X-Portal-Owner-Units": "IT Service Desk",
        }

    return _headers


def _actor(role: str = "MANAGER") -> PortalActor:
    return PortalActor(
        user_id="manager.demo",
        display_name="Manager Demo",
        role=role,
        owner_unit_ids=["IT Service Desk"],
    )


def _document(status: str = "DRAFT") -> KnowledgeDocumentRecord:
    return KnowledgeDocumentRecord(
        document_id="doc-test",
        title="Test",
        summary="",
        category="",
        owner_unit_id="IT Service Desk",
        business_contact="",
        audience_type="ALL_EMPLOYEES",
        audience_group_ids=[],
        draft_version_id="ver-test",
        current_published_version_id=None,
        status=status,
        etag='W/"etag-1"',
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        created_by="manager.demo",
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_by="manager.demo",
    )


def test_governed_profile_disables_relaxed_workflow() -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "demo_mode", False)
    object.__setattr__(settings, "relaxed_workflow", True)

    assert settings.effective_relaxed_workflow() is False


def test_demo_profile_keeps_relaxed_workflow_flag() -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "demo_mode", True)
    object.__setattr__(settings, "relaxed_workflow", True)

    assert settings.effective_relaxed_workflow() is True


def test_manager_sees_publish_next_action_for_approved_document() -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "demo_mode", True)
    object.__setattr__(settings, "relaxed_workflow", True)
    document = _document(status="APPROVED")
    draft = KnowledgeVersionRecord(
        version_id="ver-test",
        document_id="doc-test",
        version_number=1,
        title="Test",
        summary="",
        category="",
        owner_unit_id="IT Service Desk",
        business_contact="",
        audience_type="ALL_EMPLOYEES",
        audience_group_ids=[],
        effective_at="2026-08-01",
        review_due_at="2026-12-01",
        change_summary="",
        change_reason="",
        canonical_content="# Test",
        content_hash="abc",
        asset_slug="test",
        status="APPROVED",
        validation_summary=ValidationSummary(),
        parse_preview=None,
        etag='W/"ver-1"',
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        created_by="manager.demo",
    )
    allowed = compute_allowed_actions(
        actor=_actor("MANAGER"),
        document=document,
        draft_version=draft,
        open_review=None,
        settings=settings,
    )
    next_action = compute_next_action(allowed, document_status=document.status)

    assert "PUBLISH" in allowed
    assert next_action == "PUBLISH"


def test_governed_dashboard_requires_three_tests(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "demo_mode", False)
    object.__setattr__(settings, "relaxed_workflow", True)
    client = TestClient(create_app(settings))

    response = client.get("/api/dashboard", headers=portal_headers(role="MANAGER"))
    assert response.status_code == 200
    body = response.json()
    assert body["portal_profile"] == "GOVERNED"
    assert body["relaxed_workflow"] is False
    assert body["min_test_cases_for_review"] == 3


def test_reviewer_home_route(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.get("/api/dashboard", headers=portal_headers(role="REVIEWER"))
    assert response.json()["home_route"] == "#/reviews"


def test_auditor_capabilities_are_read_only() -> None:
    settings = PortalSettings.from_env()
    document = _document(status="IN_REVIEW")
    draft = KnowledgeVersionRecord(
        version_id="ver-test",
        document_id="doc-test",
        version_number=1,
        title="Test",
        summary="",
        category="",
        owner_unit_id="IT Service Desk",
        business_contact="",
        audience_type="ALL_EMPLOYEES",
        audience_group_ids=[],
        effective_at="2026-08-01",
        review_due_at="2026-12-01",
        change_summary="",
        change_reason="",
        canonical_content="# Test",
        content_hash="abc",
        asset_slug="test",
        status="IN_REVIEW",
        validation_summary=ValidationSummary(),
        parse_preview=None,
        etag='W/"ver-1"',
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        created_by="contributor.demo",
    )
    open_review = ReviewRecord(
        review_id="review-test",
        version_id="ver-test",
        document_id="doc-test",
        snapshot_hash="abc",
        submitted_by="contributor.demo",
        submitted_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    allowed = compute_allowed_actions(
        actor=_actor("AUDITOR"),
        document=document,
        draft_version=draft,
        open_review=open_review,
        settings=settings,
    )

    assert allowed == ["VIEW"]


def test_auditor_cannot_review_or_publish() -> None:
    actor = _actor("AUDITOR")

    with pytest.raises(Exception, match="permission to review"):
        ensure_can_review(actor, "contributor.demo", relaxed_workflow=False)

    with pytest.raises(Exception, match="permission to publish"):
        ensure_can_publish(actor)


def test_auditor_cannot_decide_review_via_api(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "relaxed_workflow", True)
    client = TestClient(create_app(settings))

    create = client.post(
        "/api/documents",
        json={
            "title": "Audit test doc",
            "summary": "",
            "category": "",
            "owner_unit_id": "IT Service Desk",
            "business_contact": "",
            "audience_type": "ALL_EMPLOYEES",
            "audience_group_ids": [],
            "effective_at": "2026-08-01",
            "review_due_at": "2026-12-01",
            "change_summary": "Initial",
            "change_reason": "Initial",
            "markdown_content": "# Audit test",
        },
        headers=portal_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
    )
    document_id = create.json()["document"]["document_id"]
    etag = create.json()["document"]["etag"]
    submit = client.post(
        f"/api/documents/{document_id}/submit-review",
        json={"etag": etag, "change_reason": "Ready"},
        headers=portal_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
    )
    review_id = submit.json()["open_review"]["review_id"]

    response = client.post(
        f"/api/reviews/{review_id}/decision",
        json={"decision": "APPROVED", "comment": "Should fail", "policy_exceptions": []},
        headers=portal_headers(role="AUDITOR", user_id="auditor.demo"),
    )
    assert response.status_code == 403


def test_contributor_cannot_list_audit_events(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.get(
        "/api/audit-events",
        headers=portal_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
    )
    assert response.status_code == 403


def test_manager_can_list_audit_events(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.get("/api/audit-events", headers=portal_headers(role="MANAGER"))
    assert response.status_code == 200


def test_dashboard_visible_nav_excludes_audit_for_contributor(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.get(
        "/api/dashboard",
        headers=portal_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
    )
    assert "audit" not in response.json()["visible_nav"]


def test_dashboard_visible_nav_includes_audit_for_auditor(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.get(
        "/api/dashboard",
        headers=portal_headers(role="AUDITOR", user_id="auditor.demo"),
    )
    body = response.json()
    assert "audit" in body["visible_nav"]
    assert "reviews" not in body["visible_nav"]


def test_contributor_cannot_view_audit_via_rbac_helper() -> None:
    with pytest.raises(Exception, match="permission to view audit"):
        ensure_can_view_audit(_actor("CONTRIBUTOR"))


def test_auditor_cannot_create_document_via_api(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.post(
        "/api/documents",
        json={
            "title": "Should fail",
            "summary": "",
            "category": "",
            "owner_unit_id": "IT Service Desk",
            "business_contact": "",
            "audience_type": "ALL_EMPLOYEES",
            "audience_group_ids": [],
            "effective_at": "2026-08-01",
            "review_due_at": "2026-12-01",
            "change_summary": "Initial",
            "change_reason": "Initial",
            "markdown_content": "# Should fail",
        },
        headers=portal_headers(role="AUDITOR", user_id="auditor.demo"),
    )
    assert response.status_code == 403


def test_auditor_cannot_list_pending_reviews(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.get(
        "/api/reviews/pending",
        headers=portal_headers(role="AUDITOR", user_id="auditor.demo"),
    )
    assert response.status_code == 403


def test_reviewer_cannot_list_releases(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.get(
        "/api/releases",
        headers=portal_headers(role="REVIEWER", user_id="reviewer.demo"),
    )
    assert response.status_code == 403


def test_dashboard_includes_capabilities(portal_headers) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    client = TestClient(create_app(settings))

    response = client.get(
        "/api/dashboard",
        headers=portal_headers(role="AUDITOR", user_id="auditor.demo"),
    )
    body = response.json()
    assert body["capabilities"]["create_document"] is False
    assert body["capabilities"]["view_audit"] is True
    assert body["capabilities"]["list_releases"] is False
