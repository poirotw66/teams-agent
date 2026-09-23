"""Independent service-catalog governance store, API, and finalize wiring."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_portal.bootstrap.container import build_portal_container
from knowledge_portal.bootstrap.register_routes import register_portal_routes
from knowledge_portal.models import (
    KnowledgeDocumentRecord,
    ReleaseManifestEntry,
    utc_now,
)
from knowledge_portal.service_catalog_artifact import write_service_catalog_artifact
from knowledge_portal.service_catalog_governance import (
    ServiceCatalogGovernanceError,
    load_approved_catalog_for_release,
    load_catalog_draft,
    save_catalog_draft,
    transition_catalog_draft,
)
from knowledge_portal.settings import PortalSettings


def _portal_settings(tmp_path: Path) -> PortalSettings:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "embedding_model", None)
    object.__setattr__(settings, "agent_api_url", None)
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "data_dir", tmp_path / "data")
    object.__setattr__(settings, "drafts_dir", tmp_path / "drafts")
    object.__setattr__(settings, "state_path", tmp_path / "portal_state.json")
    object.__setattr__(settings, "relaxed_workflow", True)
    object.__setattr__(settings, "default_tenant_id", "tenant-a")
    return settings


def _headers(
    *,
    role: str = "MANAGER",
    user_id: str = "manager.demo",
) -> dict[str, str]:
    return {
        "X-Portal-User-Id": user_id,
        "X-Portal-User-Name": user_id,
        "X-Portal-Role": role,
        "X-Portal-Owner-Units": "IT Service Desk",
        "X-Portal-Tenant-Id": "tenant-a",
    }


def _make_client(
    tmp_path: Path,
    *,
    relaxed_workflow: bool = True,
) -> tuple[TestClient, PortalSettings]:
    settings = _portal_settings(tmp_path)
    object.__setattr__(settings, "relaxed_workflow", relaxed_workflow)
    container = build_portal_container(settings)
    now = utc_now()
    doc = KnowledgeDocumentRecord(
        document_id="doc-seat",
        title="座位搬遷需求",
        owner_unit_id="IT Service Desk",
        status="PUBLISHED",
        current_published_version_id="ver-1",
        etag="etag-1",
        created_by="seed",
        updated_by="seed",
        created_at=now,
        updated_at=now,
        tenant_id="tenant-a",
    )
    asyncio.run(container.service._ctx.repository.save_document(doc))
    app = FastAPI()
    register_portal_routes(
        app,
        settings=container.settings,
        service=container.service,
        pdf_job_store=container.pdf_job_store,
        authorize=container.authorize,
        current_actor=container.current_actor,
        correlation_id=container.correlation_id,
        idempotency_key=container.idempotency_key,
        handle_errors=container.handle_errors,
    )
    return TestClient(app), settings


def test_save_and_transition_require_document_link(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    with pytest.raises(ServiceCatalogGovernanceError) as exc_info:
        save_catalog_draft(
            data_dir,
            tenant_id="tenant-a",
            services=[{"serviceId": "seat", "officialName": "座位", "aliases": []}],
            status="DRAFT",
            actor_id="u1",
        )
    assert exc_info.value.code == "CATALOG_DOCUMENT_LINK_REQUIRED"


def test_approve_requires_published_document_ids(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    save_catalog_draft(
        data_dir,
        tenant_id="tenant-a",
        services=[
            {
                "serviceId": "seat",
                "officialName": "座位搬遷",
                "aliases": ["座位遷移"],
                "documentId": "doc-seat",
            }
        ],
        status="DRAFT",
        actor_id="contributor",
    )
    transition_catalog_draft(
        data_dir,
        tenant_id="tenant-a",
        target_status="IN_REVIEW",
        actor_id="contributor",
    )
    with pytest.raises(ServiceCatalogGovernanceError) as exc_info:
        transition_catalog_draft(
            data_dir,
            tenant_id="tenant-a",
            target_status="APPROVED",
            actor_id="manager",
            published_document_ids=set(),
        )
    assert exc_info.value.code == "CATALOG_DOCUMENT_NOT_PUBLISHED"

    approved = transition_catalog_draft(
        data_dir,
        tenant_id="tenant-a",
        target_status="APPROVED",
        actor_id="manager",
        published_document_ids={"doc-seat"},
    )
    assert approved["status"] == "APPROVED"


def test_finalize_prefers_approved_governed_catalog(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    save_catalog_draft(
        data_dir,
        tenant_id="tenant-a",
        services=[
            {
                "serviceId": "seat_relocation",
                "officialName": "座位搬遷需求",
                "aliases": ["治理別名"],
                "documentId": "doc-seat",
            }
        ],
        status="DRAFT",
        actor_id="c1",
    )
    transition_catalog_draft(
        data_dir,
        tenant_id="tenant-a",
        target_status="IN_REVIEW",
        actor_id="c1",
    )
    transition_catalog_draft(
        data_dir,
        tenant_id="tenant-a",
        target_status="APPROVED",
        actor_id="m1",
        published_document_ids={"doc-seat"},
    )
    governed = load_approved_catalog_for_release(
        data_dir,
        tenant_id="tenant-a",
        release_id="release-1",
        published_document_ids={"doc-seat"},
    )
    assert governed is not None
    release_dir = tmp_path / "releases" / "release-1"
    release_dir.mkdir(parents=True)
    write_service_catalog_artifact(
        release_dir,
        release_id="release-1",
        tenant_id="tenant-a",
        manifest=[
            ReleaseManifestEntry(
                document_id="doc-seat",
                version_id="v1",
                title="座位搬遷需求",
                content_hash="h1",
                source_path="sources/doc-seat.md",
                source_aliases=["文件別名"],
            )
        ],
        governed_payload=governed,
    )
    packaged = json.loads(
        (release_dir / "catalog" / "service_catalog.json").read_text(encoding="utf-8")
    )
    assert packaged["services"][0]["aliases"] == ["治理別名"]
    assert packaged["releaseId"] == "release-1"
    assert packaged.get("source") == "governed_catalog_draft"


def test_catalog_api_draft_submit_approve_flow(tmp_path: Path) -> None:
    client, settings = _make_client(tmp_path)

    upsert = client.put(
        "/api/catalog/draft",
        headers=_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
        json={
            "services": [
                {
                    "serviceId": "seat_relocation",
                    "officialName": "座位搬遷需求",
                    "aliases": ["座位遷移"],
                    "documentId": "doc-seat",
                }
            ]
        },
    )
    assert upsert.status_code == 200, upsert.text
    assert upsert.json()["draft"]["status"] == "DRAFT"

    submit = client.post(
        "/api/catalog/submit-review",
        headers=_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
        json={},
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["draft"]["status"] == "IN_REVIEW"

    approve = client.post(
        "/api/catalog/approve",
        headers=_headers(role="MANAGER", user_id="manager.demo"),
        json={"reason": "ok"},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["draft"]["status"] == "APPROVED"

    loaded = load_catalog_draft(settings.data_dir, tenant_id="tenant-a")
    assert loaded is not None
    assert loaded["status"] == "APPROVED"


def test_catalog_api_blocks_self_approve_when_not_relaxed(tmp_path: Path) -> None:
    client, _settings = _make_client(tmp_path, relaxed_workflow=False)

    assert (
        client.put(
            "/api/catalog/draft",
            headers=_headers(role="MANAGER", user_id="manager.self"),
            json={
                "services": [
                    {
                        "serviceId": "seat_relocation",
                        "officialName": "座位搬遷需求",
                        "aliases": [],
                        "documentId": "doc-seat",
                    }
                ]
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/catalog/submit-review",
            headers=_headers(role="MANAGER", user_id="manager.self"),
            json={},
        ).status_code
        == 200
    )

    blocked = client.post(
        "/api/catalog/approve",
        headers=_headers(role="MANAGER", user_id="manager.self"),
        json={"reason": "self"},
    )
    assert blocked.status_code == 403, blocked.text

    allowed = client.post(
        "/api/catalog/approve",
        headers=_headers(role="MANAGER", user_id="manager.other"),
        json={"reason": "peer"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["draft"]["status"] == "APPROVED"


def test_catalog_api_blocks_approver_who_last_published_linked_document(
    tmp_path: Path,
) -> None:
    """Catalog approver must not be document.updated_by (publish actor) when not relaxed."""
    settings = _portal_settings(tmp_path)
    object.__setattr__(settings, "relaxed_workflow", False)
    container = build_portal_container(settings)
    now = utc_now()
    doc = KnowledgeDocumentRecord(
        document_id="doc-seat",
        title="座位搬遷需求",
        owner_unit_id="IT Service Desk",
        status="PUBLISHED",
        current_published_version_id="ver-1",
        etag="etag-1",
        created_by="seed",
        updated_by="manager.publisher",
        created_at=now,
        updated_at=now,
        tenant_id="tenant-a",
    )
    asyncio.run(container.service._ctx.repository.save_document(doc))
    app = FastAPI()
    register_portal_routes(
        app,
        settings=settings,
        service=container.service,
        pdf_job_store=container.pdf_job_store,
        authorize=container.authorize,
        current_actor=container.current_actor,
        correlation_id=container.correlation_id,
        idempotency_key=container.idempotency_key,
        handle_errors=container.handle_errors,
    )
    client = TestClient(app)

    assert (
        client.put(
            "/api/catalog/draft",
            headers=_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
            json={
                "services": [
                    {
                        "serviceId": "seat_relocation",
                        "officialName": "座位搬遷需求",
                        "aliases": [],
                        "documentId": "doc-seat",
                    }
                ]
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/catalog/submit-review",
            headers=_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
            json={},
        ).status_code
        == 200
    )

    blocked = client.post(
        "/api/catalog/approve",
        headers=_headers(role="MANAGER", user_id="manager.publisher"),
        json={"reason": "self-publish"},
    )
    assert blocked.status_code == 403, blocked.text

    allowed = client.post(
        "/api/catalog/approve",
        headers=_headers(role="MANAGER", user_id="manager.other"),
        json={"reason": "peer"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["draft"]["status"] == "APPROVED"


def test_catalog_bridge_paths_are_allowlisted() -> None:
    from ai_ops_backoffice.knowledge_bridge.capabilities import capability_for_portal_path
    from ai_ops_backoffice.knowledge_bridge.errors import assert_allowlisted

    assert assert_allowlisted("catalog") == "catalog"
    assert assert_allowlisted("catalog/draft") == "catalog/draft"
    assert assert_allowlisted("catalog/submit-review") == "catalog/submit-review"
    assert assert_allowlisted("catalog/approve") == "catalog/approve"
    assert assert_allowlisted("catalog/reject") == "catalog/reject"
    assert capability_for_portal_path("GET", "catalog") == "knowledge.read"
    assert capability_for_portal_path("PUT", "catalog/draft") == "knowledge.edit"
    assert capability_for_portal_path("POST", "catalog/submit-review") == "knowledge.submit"
    assert capability_for_portal_path("POST", "catalog/approve") == "knowledge.catalog.approve"
    assert capability_for_portal_path("POST", "catalog/reject") == "knowledge.review"


def test_memory_catalog_store_is_shared_across_instances(tmp_path: Path) -> None:
    """Two store handles sharing one dict simulate multi-instance Backoffice."""
    from knowledge_portal.service_catalog_draft_store import MemoryCatalogDraftStore

    shared: dict[str, dict] = {}
    instance_a = MemoryCatalogDraftStore(shared)
    instance_b = MemoryCatalogDraftStore(shared)
    services = [
        {
            "serviceId": "seat_relocation",
            "officialName": "座位搬遷需求",
            "aliases": ["座位遷移"],
            "documentId": "doc-seat",
        }
    ]
    save_catalog_draft(
        tmp_path,
        tenant_id="tenant-a",
        services=services,
        status="DRAFT",
        actor_id="writer-a",
        store=instance_a,
    )
    loaded = load_catalog_draft(tmp_path, tenant_id="tenant-a", store=instance_b)
    assert loaded is not None
    assert loaded["status"] == "DRAFT"
    assert loaded["updatedBy"] == "writer-a"

    transition_catalog_draft(
        tmp_path,
        tenant_id="tenant-a",
        target_status="IN_REVIEW",
        actor_id="writer-b",
        store=instance_b,
    )
    reread = load_catalog_draft(tmp_path, tenant_id="tenant-a", store=instance_a)
    assert reread is not None
    assert reread["status"] == "IN_REVIEW"
    assert reread["updatedBy"] == "writer-b"


def test_firestore_catalog_store_round_trip_with_fake_client(tmp_path: Path) -> None:
    from fake_firestore import FakeFirestoreClient

    from knowledge_portal.service_catalog_draft_store import (
        FirestoreCatalogDraftStore,
        build_catalog_draft_store,
    )

    settings = _portal_settings(tmp_path)
    object.__setattr__(settings, "repository_mode", "FIRESTORE")
    object.__setattr__(settings, "catalog_drafts_collection", "knowledge_catalog_drafts")
    client = FakeFirestoreClient()
    store = FirestoreCatalogDraftStore(settings, client=client)
    assert build_catalog_draft_store(settings, firestore_client=client).backend_name == (
        "FIRESTORE"
    )

    services = [
        {
            "serviceId": "seat_relocation",
            "officialName": "座位搬遷需求",
            "aliases": [],
            "documentId": "doc-seat",
        }
    ]
    save_catalog_draft(
        settings.data_dir,
        tenant_id="tenant-a",
        services=services,
        status="DRAFT",
        actor_id="contributor.demo",
        store=store,
    )
    loaded = load_catalog_draft(
        settings.data_dir,
        tenant_id="tenant-a",
        store=FirestoreCatalogDraftStore(settings, client=client),
    )
    assert loaded is not None
    assert loaded["status"] == "DRAFT"
    assert client.document_count("knowledge_catalog_drafts/") == 1

    # Non-FIRESTORE modes keep FILE local-dev fallback.
    object.__setattr__(settings, "repository_mode", "MEMORY")
    assert build_catalog_draft_store(settings).backend_name == "FILE"


def test_catalog_get_reports_file_governance_backend(tmp_path: Path) -> None:
    client, _settings = _make_client(tmp_path)
    response = client.get("/api/catalog", headers=_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["governance"] == "FILE"
    assert any("FIRESTORE" in gap for gap in body["remainingGaps"])


def test_catalog_reviewer_can_reject_but_not_approve(tmp_path: Path) -> None:
    client, _settings = _make_client(tmp_path, relaxed_workflow=False)
    assert (
        client.put(
            "/api/catalog/draft",
            headers=_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
            json={
                "services": [
                    {
                        "serviceId": "seat_relocation",
                        "officialName": "座位搬遷需求",
                        "aliases": [],
                        "documentId": "doc-seat",
                    }
                ]
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/catalog/submit-review",
            headers=_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
            json={},
        ).status_code
        == 200
    )
    blocked = client.post(
        "/api/catalog/approve",
        headers=_headers(role="REVIEWER", user_id="reviewer.demo"),
        json={"reason": "no"},
    )
    assert blocked.status_code == 403, blocked.text

    # Reset to IN_REVIEW via a fresh draft→submit for reject path.
    assert (
        client.put(
            "/api/catalog/draft",
            headers=_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
            json={
                "services": [
                    {
                        "serviceId": "seat_relocation",
                        "officialName": "座位搬遷需求",
                        "aliases": [],
                        "documentId": "doc-seat",
                    }
                ]
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/catalog/submit-review",
            headers=_headers(role="CONTRIBUTOR", user_id="contributor.demo"),
            json={},
        ).status_code
        == 200
    )
    rejected = client.post(
        "/api/catalog/reject",
        headers=_headers(role="REVIEWER", user_id="reviewer.demo"),
        json={"reason": "needs edits"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["draft"]["status"] == "REJECTED"


def test_catalog_self_approve_allowed_when_relaxed(tmp_path: Path) -> None:
    client, _settings = _make_client(tmp_path, relaxed_workflow=True)
    headers = _headers(role="MANAGER", user_id="manager.self")
    assert (
        client.put(
            "/api/catalog/draft",
            headers=headers,
            json={
                "services": [
                    {
                        "serviceId": "seat_relocation",
                        "officialName": "座位搬遷需求",
                        "aliases": [],
                        "documentId": "doc-seat",
                    }
                ]
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/catalog/submit-review",
            headers=headers,
            json={},
        ).status_code
        == 200
    )
    approved = client.post(
        "/api/catalog/approve",
        headers=headers,
        json={"reason": "relaxed"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["draft"]["status"] == "APPROVED"


def test_production_finalize_requires_approved_catalog_when_configured(
    tmp_path: Path,
) -> None:
    from knowledge_portal.publisher_finalize import (
        ReleaseBuildError,
        require_approved_catalog_for_production_if_needed,
    )

    settings = _portal_settings(tmp_path)
    object.__setattr__(settings, "release_purpose", "PRODUCTION")
    object.__setattr__(settings, "require_approved_catalog_for_production", True)
    object.__setattr__(settings, "relaxed_workflow", False)

    with pytest.raises(ReleaseBuildError, match="APPROVED service catalog"):
        require_approved_catalog_for_production_if_needed(
            settings,
            governed_catalog=None,
        )

    require_approved_catalog_for_production_if_needed(
        settings,
        governed_catalog={"releaseId": "r1", "status": "APPROVED", "services": []},
    )

    object.__setattr__(settings, "require_approved_catalog_for_production", False)
    object.__setattr__(settings, "require_dual_approval", True)
    with pytest.raises(ReleaseBuildError, match="APPROVED service catalog"):
        require_approved_catalog_for_production_if_needed(
            settings,
            governed_catalog=None,
        )

    object.__setattr__(settings, "release_purpose", "E2E")
    require_approved_catalog_for_production_if_needed(
        settings,
        governed_catalog=None,
    )
