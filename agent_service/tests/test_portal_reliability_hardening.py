from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.documents import DocumentChunk
from agent_service.knowledge_release import (
    release_index_path,
    write_active_release_pointer,
)
from agent_service.retrieval import HybridIndex
from agent_service.settings import RagSettings
from knowledge_portal.firestore_repository import FirestorePortalRepository
from knowledge_portal.models import (
    CreateDocumentRequest,
    PortalActor,
    PublishRequest,
    RemoveDocumentRequest,
    ReviewDecisionRequest,
    RollbackRequest,
    SubmitReviewRequest,
)
from knowledge_portal.publisher import ReleaseBuildError
from knowledge_portal.rbac import PortalPermissionError, ensure_can_review
from knowledge_portal.repository import build_repository
from knowledge_portal.service import PortalService
from knowledge_portal.services.context import IdempotencyConflictError
from knowledge_portal.settings import PortalSettings


def _create_test_index(path: Path, chunks_data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = [
        DocumentChunk(
            chunk_id=c["chunk_id"],
            source_path=c["source_path"],
            title=c["title"],
            content=c["content"],
        )
        for c in chunks_data
    ]
    index = HybridIndex(chunks=chunks, embedding_model=None)
    index.save(path)


def _setup_test_portal(tmp_path: Path) -> tuple[PortalService, PortalSettings]:
    data_dir = tmp_path / "portal_data"
    release_dir = tmp_path / "releases"
    drafts_dir = tmp_path / "drafts"

    settings = PortalSettings.from_env()
    object.__setattr__(settings, "data_dir", data_dir)
    object.__setattr__(settings, "state_path", data_dir / "portal_state.json")
    object.__setattr__(settings, "release_artifact_dir", release_dir)
    object.__setattr__(settings, "drafts_dir", drafts_dir)
    object.__setattr__(settings, "embedding_model", None)
    object.__setattr__(settings, "agent_api_url", "http://agent-test-service:8000")
    object.__setattr__(settings, "agent_api_token", "test-agent-token")
    object.__setattr__(settings, "relaxed_workflow", True)

    service = PortalService(settings, build_repository(settings))
    return service, settings


# --------------------------------------------------------------------------
# 1. P1: Cross-unit rollback protection & manifest title masking
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cross_unit_rollback_blocked_and_title_masked(tmp_path: Path) -> None:
    service, _ = _setup_test_portal(tmp_path)

    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )
    manager_a = PortalActor(
        user_id="mgr-a",
        display_name="Manager A",
        role="MANAGER",
        owner_unit_ids=["UNIT-A"],
    )
    manager_b = PortalActor(
        user_id="mgr-b",
        display_name="Manager B",
        role="MANAGER",
        owner_unit_ids=["UNIT-B"],
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(status_code=200, json={"status": "reloaded"})

        # Create & publish Doc A (UNIT-A)
        doc_a = await service.create_document(
            manager_a,
            CreateDocumentRequest(
                title="Confidential Doc A",
                summary="Summary A",
                category="Policy",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init A",
                markdown_content="Content A",
            ),
            correlation_id="c-1",
        )
        await service.submit_for_review(
            manager_a,
            doc_a.document.document_id,
            SubmitReviewRequest(etag=doc_a.document.etag, change_reason="Review A"),
            correlation_id="c-2",
        )
        rev_a = (await service.list_pending_reviews(platform_admin)).items[0].review_id
        await service.decide_review(
            platform_admin,
            rev_a,
            ReviewDecisionRequest(decision="APPROVED", comment="OK A"),
            correlation_id="c-3",
        )
        rel_1 = await service.publish_version(
            manager_a,
            doc_a.document.document_id,
            PublishRequest(version_id=doc_a.draft_version.version_id, reason="Pub A"),
            correlation_id="c-4",
        )

        # Create & publish Doc B (UNIT-B)
        doc_b = await service.create_document(
            manager_b,
            CreateDocumentRequest(
                title="Confidential Doc B",
                summary="Summary B",
                category="Policy",
                owner_unit_id="UNIT-B",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init B",
                markdown_content="Content B",
            ),
            correlation_id="c-5",
        )
        await service.submit_for_review(
            manager_b,
            doc_b.document.document_id,
            SubmitReviewRequest(etag=doc_b.document.etag, change_reason="Review B"),
            correlation_id="c-6",
        )
        rev_b = next(
            item.review_id
            for item in (await service.list_pending_reviews(platform_admin)).items
            if item.document_id == doc_b.document.document_id
        )
        await service.decide_review(
            platform_admin,
            rev_b,
            ReviewDecisionRequest(decision="APPROVED", comment="OK B"),
            correlation_id="c-7",
        )
        rel_2 = await service.publish_version(
            manager_b,
            doc_b.document.document_id,
            PublishRequest(version_id=doc_b.draft_version.version_id, reason="Pub B"),
            correlation_id="c-8",
        )

        # Verification 1: Manager A listing releases sees Doc B title masked as [Restricted Document]
        releases_seen_by_a = await service.list_releases(manager_a)
        rel_2_seen = next(r for r in releases_seen_by_a if r.release_id == rel_2.release_id)
        entry_b = next(e for e in rel_2_seen.manifest if e.document_id == doc_b.document.document_id)
        assert entry_b.title == "[Restricted Document]"

        entry_a = next(e for e in rel_2_seen.manifest if e.document_id == doc_a.document.document_id)
        assert entry_a.title == "Confidential Doc A"

        # Verification 2: Manager A cannot rollback release 2 to release 1 (affects Doc B from UNIT-B)
        with pytest.raises(PortalPermissionError, match="Global rollback affects documents from other units"):
            await service.rollback_release(
                manager_a,
                RollbackRequest(release_id=rel_1.release_id, reason="A trying rollback"),
                correlation_id="c-9",
            )

        # Verification 3: Platform Admin CAN perform rollback
        rolled = await service.rollback_release(
            platform_admin,
            RollbackRequest(release_id=rel_1.release_id, reason="Platform rollback"),
            correlation_id="c-10",
        )
        assert rolled.status == "ACTIVE"


# --------------------------------------------------------------------------
# 2. P1: Concurrent publishing serialization & manifest integrity
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_publishing_serialization(tmp_path: Path) -> None:
    service, _ = _setup_test_portal(tmp_path)
    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        async def delayed_post(*args, **kwargs):
            await asyncio.sleep(0.05)
            return httpx.Response(status_code=200, json={"status": "reloaded"})

        mock_post.side_effect = delayed_post

        doc1 = await service.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc 1",
                summary="Sum 1",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init 1",
                markdown_content="Content 1",
            ),
            correlation_id="c-1",
        )
        await service.submit_for_review(
            platform_admin,
            doc1.document.document_id,
            SubmitReviewRequest(etag=doc1.document.etag, change_reason="R1"),
            correlation_id="c-2",
        )
        rev1 = (await service.list_pending_reviews(platform_admin)).items[0].review_id
        await service.decide_review(
            platform_admin,
            rev1,
            ReviewDecisionRequest(decision="APPROVED", comment="OK"),
            correlation_id="c-3",
        )

        doc2 = await service.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc 2",
                summary="Sum 2",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init 2",
                markdown_content="Content 2",
            ),
            correlation_id="c-4",
        )
        await service.submit_for_review(
            platform_admin,
            doc2.document.document_id,
            SubmitReviewRequest(etag=doc2.document.etag, change_reason="R2"),
            correlation_id="c-5",
        )
        rev2 = next(
            i.review_id
            for i in (await service.list_pending_reviews(platform_admin)).items
            if i.document_id == doc2.document.document_id
        )
        await service.decide_review(
            platform_admin,
            rev2,
            ReviewDecisionRequest(decision="APPROVED", comment="OK"),
            correlation_id="c-6",
        )

        # Trigger concurrent publish calls simultaneously
        t1 = service.publish_version(
            platform_admin,
            doc1.document.document_id,
            PublishRequest(version_id=doc1.draft_version.version_id, reason="Pub 1"),
            correlation_id="c-pub-1",
        )
        t2 = service.publish_version(
            platform_admin,
            doc2.document.document_id,
            PublishRequest(version_id=doc2.draft_version.version_id, reason="Pub 2"),
            correlation_id="c-pub-2",
        )

        res1, res2 = await asyncio.gather(t1, t2)
        assert res1.status in {"ACTIVE", "INACTIVE"}
        assert res2.status in {"ACTIVE", "INACTIVE"}

        # Verification: Active release manifest contains BOTH documents
        active_rel_id = await service._releases._ctx.repository.get_active_release_id()
        active_rel = await service._releases._ctx.repository.get_release(active_rel_id)
        assert active_rel.status == "ACTIVE"
        active_doc_ids = {e.document_id for e in active_rel.manifest}
        assert doc1.document.document_id in active_doc_ids
        assert doc2.document.document_id in active_doc_ids

        # Exactly 1 active release exists
        releases = await service.list_releases(platform_admin)
        active_count = sum(1 for r in releases if r.status == "ACTIVE")
        assert active_count == 1


# --------------------------------------------------------------------------
# 3. P1: Firestore pending reviews query contract test
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_firestore_repository_list_pending_reviews_query() -> None:
    settings = PortalSettings.from_env()
    mock_db = MagicMock()
    repo = FirestorePortalRepository(settings, client=mock_db)

    from datetime import datetime, timezone

    review_pending = {
        "review_id": "rev-1",
        "document_id": "doc-1",
        "version_id": "ver-1",
        "snapshot_hash": "hash-1",
        "submitted_by": "user-1",
        "submitted_at": datetime.now(timezone.utc),
        "decision": None,
        "reviewer_id": None,
        "decided_at": None,
        "comment": "",
        "policy_exceptions": [],
    }
    review_decided = {
        "review_id": "rev-2",
        "document_id": "doc-2",
        "version_id": "ver-2",
        "snapshot_hash": "hash-2",
        "submitted_by": "user-2",
        "submitted_at": datetime.now(timezone.utc),
        "decision": "APPROVED",
        "reviewer_id": "mgr-1",
        "decided_at": datetime.now(timezone.utc),
        "comment": "Approved",
        "policy_exceptions": [],
    }

    doc_mock1 = MagicMock()
    doc_mock1.to_dict.return_value = review_pending
    doc_mock2 = MagicMock()
    doc_mock2.to_dict.return_value = review_decided

    async def async_stream():
        yield doc_mock1
        yield doc_mock2

    mock_collection = MagicMock()
    mock_collection.stream.side_effect = async_stream
    mock_db.collection.return_value = mock_collection

    admin_actor = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )
    pending_items = await repo.list_pending_reviews(admin_actor)
    assert len(pending_items) == 1
    assert pending_items[0].review_id == "rev-1"
    assert pending_items[0].decision is None


# --------------------------------------------------------------------------
# 4. P1: Unpublishing last document creates empty release & notifies agent
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unpublish_last_document_clears_agent_knowledge(tmp_path: Path) -> None:
    service, _ = _setup_test_portal(tmp_path)
    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            status_code=200, json={"status": "reloaded", "chunks": 1}
        )

        doc = await service.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Sole Doc",
                summary="Sum",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Sole doc",
                markdown_content="Some content",
            ),
            correlation_id="c-1",
        )
        await service.submit_for_review(
            platform_admin,
            doc.document.document_id,
            SubmitReviewRequest(etag=doc.document.etag, change_reason="Review"),
            correlation_id="c-2",
        )
        rev_id = (await service.list_pending_reviews(platform_admin)).items[0].review_id
        await service.decide_review(
            platform_admin,
            rev_id,
            ReviewDecisionRequest(decision="APPROVED", comment="OK"),
            correlation_id="c-3",
        )
        await service.publish_version(
            platform_admin,
            doc.document.document_id,
            PublishRequest(version_id=doc.draft_version.version_id, reason="Pub"),
            correlation_id="c-4",
        )

        mock_post.reset_mock()
        mock_post.return_value = httpx.Response(
            status_code=200, json={"status": "reloaded", "chunks": 0}
        )

        # Unpublish the only document
        await service.unpublish_document(
            platform_admin,
            doc.document.document_id,
            RemoveDocumentRequest(reason="Unpublishing sole document"),
            correlation_id="c-5",
        )

        active_rel_id = await service._releases._ctx.repository.get_active_release_id()
        unpub_rel = await service._releases._ctx.repository.get_release(active_rel_id)
        assert len(unpub_rel.manifest) == 0
        assert unpub_rel.status == "ACTIVE"

        mock_post.assert_called_once()
        called_payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert called_payload["releaseId"] == unpub_rel.release_id


# --------------------------------------------------------------------------
# 5. P1: Stale reload rejection & active release sync enforcement
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sync_agent_release_only_allows_active_release(tmp_path: Path) -> None:
    service, _ = _setup_test_portal(tmp_path)
    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(status_code=200, json={"status": "reloaded"})

        doc = await service.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc",
                summary="Sum",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init",
                markdown_content="Content v1",
            ),
            correlation_id="c-1",
        )
        await service.submit_for_review(
            platform_admin,
            doc.document.document_id,
            SubmitReviewRequest(etag=doc.document.etag, change_reason="R1"),
            correlation_id="c-2",
        )
        rev1 = (await service.list_pending_reviews(platform_admin)).items[0].review_id
        await service.decide_review(
            platform_admin, rev1, ReviewDecisionRequest(decision="APPROVED", comment="OK"), correlation_id="c-3"
        )
        rel_1 = await service.publish_version(
            platform_admin,
            doc.document.document_id,
            PublishRequest(version_id=doc.draft_version.version_id, reason="P1"),
            correlation_id="c-4",
        )

        doc2 = await service.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc 2",
                summary="Sum 2",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init 2",
                markdown_content="Content 2",
            ),
            correlation_id="c-5",
        )
        await service.submit_for_review(
            platform_admin,
            doc2.document.document_id,
            SubmitReviewRequest(etag=doc2.document.etag, change_reason="R2"),
            correlation_id="c-6",
        )
        rev2 = next(
            i.review_id
            for i in (await service.list_pending_reviews(platform_admin)).items
            if i.document_id == doc2.document.document_id
        )
        await service.decide_review(
            platform_admin, rev2, ReviewDecisionRequest(decision="APPROVED", comment="OK"), correlation_id="c-7"
        )
        rel_2 = await service.publish_version(
            platform_admin,
            doc2.document.document_id,
            PublishRequest(version_id=doc2.draft_version.version_id, reason="P2"),
            correlation_id="c-8",
        )
        assert rel_2.status == "ACTIVE"

        # Active is rel_2. Trying to sync rel_1 MUST raise ValueError
        with pytest.raises(ValueError, match="is not the current active release"):
            await service.sync_agent_release(platform_admin, rel_1.release_id, correlation_id="c-sync-err")


def test_agent_rejects_stale_reload_request(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    releases_dir = tmp_path / "releases"
    bundled_index_path = data_dir / "index" / "chunks.json"

    _create_test_index(bundled_index_path, [{"chunk_id": "c1", "source_path": "d.md", "title": "T", "content": "C"}])
    _create_test_index(release_index_path(releases_dir, "release-active"), [{"chunk_id": "c2", "source_path": "d.md", "title": "Active", "content": "C"}])
    _create_test_index(release_index_path(releases_dir, "release-stale"), [{"chunk_id": "c3", "source_path": "d.md", "title": "Stale", "content": "C"}])

    write_active_release_pointer(releases_dir, "release-active")

    settings = RagSettings(
        data_dir=data_dir,
        index_path=bundled_index_path,
        auto_build_index=False,
        knowledge_release_mode="AUTO",
        knowledge_release_dir=releases_dir,
        service_token="test-token",
        model=None,
        agent_model=None,
        embedding_model=None,
    )

    app = create_app(settings)
    with TestClient(app) as client:
        # Reloading stale release must fail with 409
        resp = client.post(
            "/admin/reload-knowledge",
            headers={"Authorization": "Bearer test-token"},
            json={"releaseId": "release-stale"},
        )
        assert resp.status_code == 409
        assert "Stale deployment request" in resp.json()["detail"]

        # Reloading active release succeeds
        ok_resp = client.post(
            "/admin/reload-knowledge",
            headers={"Authorization": "Bearer test-token"},
            json={"release_id": "release-active", "reason": "Syncing active"},
        )
        assert ok_resp.status_code == 200
        assert ok_resp.json()["releaseId"] == "release-active"


# --------------------------------------------------------------------------
# 6. P1: Multi-replica auto-synchronization & status endpoint
# --------------------------------------------------------------------------
def test_multi_replica_auto_sync_on_request(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    releases_dir = tmp_path / "releases"
    bundled_index_path = data_dir / "index" / "chunks.json"

    _create_test_index(bundled_index_path, [{"chunk_id": "c1", "source_path": "d.md", "title": "Bundled", "content": "Initial"}])
    _create_test_index(release_index_path(releases_dir, "release-v1"), [{"chunk_id": "c2", "source_path": "d.md", "title": "V1", "content": "V1 content"}])
    _create_test_index(release_index_path(releases_dir, "release-v2"), [{"chunk_id": "c3", "source_path": "d.md", "title": "V2", "content": "V2 content"}])

    write_active_release_pointer(releases_dir, "release-v1")

    settings = RagSettings(
        data_dir=data_dir,
        index_path=bundled_index_path,
        auto_build_index=False,
        knowledge_release_mode="AUTO",
        knowledge_release_dir=releases_dir,
        service_token="test-token",
        model=None,
        agent_model=None,
        embedding_model=None,
    )

    app1 = create_app(settings)
    with TestClient(app1) as client1:
        ready1 = client1.get("/readyz").json()
        assert ready1["knowledgeReleaseId"] == "release-v1"

        app2 = create_app(settings)
        with TestClient(app2) as client2:
            status2 = client2.get(
                "/admin/knowledge-status",
                headers={"Authorization": "Bearer test-token"},
            ).json()
            assert status2["currentReleaseId"] == "release-v1"
            assert status2["inSync"] is True

            # Portal publishes release-v2: writes pointer and notifies Replica 1
            write_active_release_pointer(releases_dir, "release-v2")
            reload_resp = client1.post(
                "/admin/reload-knowledge",
                headers={"Authorization": "Bearer test-token"},
                json={"releaseId": "release-v2"},
            )
            assert reload_resp.status_code == 200

            # Replica 2 auto-syncs on next request
            ready2_after = client2.get("/readyz").json()
            assert ready2_after["knowledgeReleaseId"] == "release-v2"

            status2_after = client2.get(
                "/admin/knowledge-status",
                headers={"Authorization": "Bearer test-token"},
            ).json()
            assert status2_after["currentReleaseId"] == "release-v2"
            assert status2_after["targetReleaseId"] == "release-v2"
            assert status2_after["inSync"] is True


# --------------------------------------------------------------------------
# 7. P2: Idempotency conflict checking with different payloads
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idempotency_detects_conflicts(tmp_path: Path) -> None:
    service, _ = _setup_test_portal(tmp_path)
    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    req1 = CreateDocumentRequest(
        title="Doc Original",
        summary="Sum",
        category="General",
        owner_unit_id="UNIT-A",
        effective_at="2026-09-01",
        review_due_at="2027-09-01",
        change_reason="Original",
        markdown_content="Payload 1",
    )
    req2_different = CreateDocumentRequest(
        title="Doc Altered",
        summary="Different",
        category="General",
        owner_unit_id="UNIT-A",
        effective_at="2026-09-01",
        review_due_at="2027-09-01",
        change_reason="Altered",
        markdown_content="Payload 2",
    )

    res1 = await service.create_document(
        platform_admin, req1, correlation_id="c-1", idempotency_key="key-xyz"
    )

    res1_retry = await service.create_document(
        platform_admin, req1, correlation_id="c-2", idempotency_key="key-xyz"
    )
    assert res1_retry.document.document_id == res1.document.document_id

    with pytest.raises(IdempotencyConflictError):
        await service.create_document(
            platform_admin, req2_different, correlation_id="c-3", idempotency_key="key-xyz"
        )


# --------------------------------------------------------------------------
# 8. P2: RBAC strict self-review prevention
# --------------------------------------------------------------------------
def test_rbac_strictly_forbids_self_review() -> None:
    reviewer = PortalActor(
        user_id="reviewer-1",
        display_name="Reviewer One",
        role="REVIEWER",
        owner_unit_ids=["UNIT-A"],
    )
    manager = PortalActor(
        user_id="mgr-1",
        display_name="Manager One",
        role="MANAGER",
        owner_unit_ids=["UNIT-A"],
    )
    platform = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    with pytest.raises(PortalPermissionError, match="Reviewers and managers cannot approve their own submissions"):
        ensure_can_review(reviewer, submitted_by="reviewer-1", relaxed_workflow=False)

    with pytest.raises(PortalPermissionError, match="Reviewers and managers cannot approve their own submissions"):
        ensure_can_review(manager, submitted_by="mgr-1", relaxed_workflow=False)

    ensure_can_review(reviewer, submitted_by="other-user", relaxed_workflow=False)
    ensure_can_review(manager, submitted_by="other-user", relaxed_workflow=False)
    ensure_can_review(platform, submitted_by="admin-1", relaxed_workflow=False)


# --------------------------------------------------------------------------
# 9. P1: Cross-instance publish coordination
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cross_instance_concurrent_publish_coordination(tmp_path: Path) -> None:
    service1, settings = _setup_test_portal(tmp_path)
    # Create second service instance sharing the exact same repository
    service2 = PortalService(settings, service1._ctx.repository)

    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(status_code=200, json={"status": "reloaded"})

        # Create and approve doc1
        doc1 = await service1.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc 1",
                summary="Sum 1",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init 1",
                markdown_content="Content 1",
            ),
            correlation_id="c-1",
        )
        await service1.submit_for_review(
            platform_admin,
            doc1.document.document_id,
            SubmitReviewRequest(etag=doc1.document.etag, change_reason="Review 1"),
            correlation_id="c-2",
        )
        rev1 = (await service1.list_pending_reviews(platform_admin)).items[0].review_id
        await service1.decide_review(
            platform_admin,
            rev1,
            ReviewDecisionRequest(decision="APPROVED", comment="OK 1"),
            correlation_id="c-3",
        )

        # Create and approve doc2
        doc2 = await service2.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc 2",
                summary="Sum 2",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init 2",
                markdown_content="Content 2",
            ),
            correlation_id="c-4",
        )
        await service2.submit_for_review(
            platform_admin,
            doc2.document.document_id,
            SubmitReviewRequest(etag=doc2.document.etag, change_reason="Review 2"),
            correlation_id="c-5",
        )
        rev2 = (await service2.list_pending_reviews(platform_admin)).items[0].review_id
        await service2.decide_review(
            platform_admin,
            rev2,
            ReviewDecisionRequest(decision="APPROVED", comment="OK 2"),
            correlation_id="c-6",
        )

        # Publish concurrently from service1 and service2
        res1, res2 = await asyncio.gather(
            service1.publish_version(
                platform_admin,
                doc1.document.document_id,
                PublishRequest(version_id=doc1.draft_version.version_id, reason="Pub 1"),
                correlation_id="c-pub-1",
            ),
            service2.publish_version(
                platform_admin,
                doc2.document.document_id,
                PublishRequest(version_id=doc2.draft_version.version_id, reason="Pub 2"),
                correlation_id="c-pub-2",
            ),
        )

        # Active release pointer must point to the winning active release
        active_id = await service1._ctx.repository.get_active_release_id()
        assert active_id in (res1.release_id, res2.release_id)

        # The active release must contain BOTH documents in its manifest!
        active_rel = await service1._ctx.repository.get_release(active_id)
        assert active_rel is not None
        manifest_doc_ids = {entry.document_id for entry in active_rel.manifest}
        assert doc1.document.document_id in manifest_doc_ids
        assert doc2.document.document_id in manifest_doc_ids

        # Exactly one release should have status ACTIVE
        releases = await service1.list_releases(platform_admin)
        active_count = sum(1 for r in releases if r.status == "ACTIVE")
        assert active_count == 1


# --------------------------------------------------------------------------
# 10. P1: Unpublish failure leaves document published and retryable
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unpublish_failure_leaves_document_published(tmp_path: Path) -> None:
    service, _ = _setup_test_portal(tmp_path)
    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(status_code=200, json={"status": "reloaded"})

        doc = await service.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc To Unpublish",
                summary="Sum",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init",
                markdown_content="Content",
            ),
            correlation_id="c-1",
        )
        await service.submit_for_review(
            platform_admin,
            doc.document.document_id,
            SubmitReviewRequest(etag=doc.document.etag, change_reason="Review"),
            correlation_id="c-2",
        )
        rev_id = (await service.list_pending_reviews(platform_admin)).items[0].review_id
        await service.decide_review(
            platform_admin,
            rev_id,
            ReviewDecisionRequest(decision="APPROVED", comment="OK"),
            correlation_id="c-3",
        )
        await service.publish_version(
            platform_admin,
            doc.document.document_id,
            PublishRequest(version_id=doc.draft_version.version_id, reason="Pub"),
            correlation_id="c-4",
        )

        published_doc = await service.get_document(platform_admin, doc.document.document_id)
        assert published_doc.document.status == "PUBLISHED"
        assert published_doc.document.current_published_version_id is not None

        # Inject build release failure
        with patch.object(
            service._ctx.publisher,
            "build_release",
            side_effect=ReleaseBuildError("Injected build error"),
        ), pytest.raises(ReleaseBuildError):
            await service.unpublish_document(
                platform_admin,
                doc.document.document_id,
                RemoveDocumentRequest(reason="Test unpublish fail"),
                correlation_id="c-fail",
            )

        # Document must STILL be PUBLISHED and retain current_published_version_id
        doc_after_failure = await service.get_document(platform_admin, doc.document.document_id)
        assert doc_after_failure.document.status == "PUBLISHED"
        assert (
            doc_after_failure.document.current_published_version_id
            == published_doc.document.current_published_version_id
        )

        # Retry without build error succeeds
        await service.unpublish_document(
            platform_admin,
            doc.document.document_id,
            RemoveDocumentRequest(reason="Retry unpublish"),
            correlation_id="c-retry",
        )
        doc_after_retry = await service.get_document(platform_admin, doc.document.document_id)
        assert doc_after_retry.document.status == "UNPUBLISHED"
        assert doc_after_retry.document.current_published_version_id is None


# --------------------------------------------------------------------------
# 11. P1: Stale reload does not overwrite active release
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stale_sync_response_does_not_overwrite_active_release(tmp_path: Path) -> None:
    service, _ = _setup_test_portal(tmp_path)
    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(status_code=200, json={"status": "reloaded"})

        # Publish Doc 1 -> Release 1
        doc1 = await service.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc 1",
                summary="Sum 1",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init 1",
                markdown_content="Content 1",
            ),
            correlation_id="c-1",
        )
        await service.submit_for_review(
            platform_admin,
            doc1.document.document_id,
            SubmitReviewRequest(etag=doc1.document.etag, change_reason="Review 1"),
            correlation_id="c-2",
        )
        rev1 = (await service.list_pending_reviews(platform_admin)).items[0].review_id
        await service.decide_review(
            platform_admin,
            rev1,
            ReviewDecisionRequest(decision="APPROVED", comment="OK 1"),
            correlation_id="c-3",
        )
        rel1 = await service.publish_version(
            platform_admin,
            doc1.document.document_id,
            PublishRequest(version_id=doc1.draft_version.version_id, reason="Pub 1"),
            correlation_id="c-4",
        )

        # Publish Doc 2 -> Release 2 (now active)
        doc2 = await service.create_document(
            platform_admin,
            CreateDocumentRequest(
                title="Doc 2",
                summary="Sum 2",
                category="General",
                owner_unit_id="UNIT-A",
                effective_at="2026-09-01",
                review_due_at="2027-09-01",
                change_reason="Init 2",
                markdown_content="Content 2",
            ),
            correlation_id="c-5",
        )
        await service.submit_for_review(
            platform_admin,
            doc2.document.document_id,
            SubmitReviewRequest(etag=doc2.document.etag, change_reason="Review 2"),
            correlation_id="c-6",
        )
        rev2 = (await service.list_pending_reviews(platform_admin)).items[0].review_id
        await service.decide_review(
            platform_admin,
            rev2,
            ReviewDecisionRequest(decision="APPROVED", comment="OK 2"),
            correlation_id="c-7",
        )
        rel2 = await service.publish_version(
            platform_admin,
            doc2.document.document_id,
            PublishRequest(version_id=doc2.draft_version.version_id, reason="Pub 2"),
            correlation_id="c-8",
        )

        assert (await service._ctx.repository.get_active_release_id()) == rel2.release_id

        # Attempt to call sync_agent_release for rel1 (which is NOT active)
        with pytest.raises(ValueError, match="not the current active release"):
            await service.sync_agent_release(platform_admin, rel1.release_id, correlation_id="c-sync")


# --------------------------------------------------------------------------
# 12. P2: File repository idempotency persistence across restarts
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_file_repository_idempotency_persistence_and_concurrency(tmp_path: Path) -> None:
    data_dir = tmp_path / "portal_data"
    release_dir = tmp_path / "releases"
    drafts_dir = tmp_path / "drafts"

    settings = PortalSettings.from_env()
    object.__setattr__(settings, "repository_mode", "FILE")
    object.__setattr__(settings, "data_dir", data_dir)
    object.__setattr__(settings, "state_path", data_dir / "portal_state.json")
    object.__setattr__(settings, "release_artifact_dir", release_dir)
    object.__setattr__(settings, "drafts_dir", drafts_dir)
    object.__setattr__(settings, "embedding_model", None)
    object.__setattr__(settings, "relaxed_workflow", True)

    repo1 = build_repository(settings)
    service1 = PortalService(settings, repo1)

    platform_admin = PortalActor(
        user_id="admin-1",
        display_name="Platform Admin",
        role="PLATFORM",
        owner_unit_ids=[],
    )

    req = CreateDocumentRequest(
        title="Persisted Idempotent Doc",
        summary="Summary",
        category="General",
        owner_unit_id="UNIT-A",
        effective_at="2026-09-01",
        review_due_at="2027-09-01",
        change_reason="Init",
        markdown_content="Persistent content",
    )

    doc_created = await service1.create_document(
        platform_admin, req, correlation_id="c-1", idempotency_key="idemp-persist-1"
    )
    assert doc_created.document.document_id is not None

    # Simulate full restart of service by creating fresh repo2 and service2 from same state file
    repo2 = build_repository(settings)
    service2 = PortalService(settings, repo2)

    # Calling create_document with same idempotency key must return cached response, NOT create another doc
    doc_reloaded = await service2.create_document(
        platform_admin, req, correlation_id="c-2", idempotency_key="idemp-persist-1"
    )
    assert doc_reloaded.document.document_id == doc_created.document.document_id

    # And documents list contains exactly 1 document
    all_docs = await service2.list_documents(platform_admin)
    assert len(all_docs.items) == 1

    # Conflict with altered payload raises IdempotencyConflictError
    req_conflict = CreateDocumentRequest(
        title="Altered Doc",
        summary="Summary",
        category="General",
        owner_unit_id="UNIT-A",
        effective_at="2026-09-01",
        review_due_at="2027-09-01",
        change_reason="Init",
        markdown_content="Different content",
    )
    with pytest.raises(IdempotencyConflictError):
        await service2.create_document(
            platform_admin, req_conflict, correlation_id="c-3", idempotency_key="idemp-persist-1"
        )


# --------------------------------------------------------------------------
# 13. BU Handoff: Entra Login UI, JWT expiry tracking and zero window.prompt
# --------------------------------------------------------------------------
def test_entra_auth_ui_and_token_expiry_in_api_js() -> None:
    api_js_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ai_ops_backoffice"
        / "static"
        / "js"
        / "api.js"
    )
    content = api_js_path.read_text(encoding="utf-8")
    assert "window.prompt" not in content
    assert "showEntraLoginModal" in content
    assert "isTokenExpired" in content
    assert "getTokenExpiryDetails" in content
    assert "logout" in content

    node_script = """
    import { parseJwt, isTokenExpired, getTokenExpiryDetails, authHeaders, saveAuthHeaders } from './src/ai_ops_backoffice/static/js/api.js';

    const store = {};
    global.sessionStorage = {
      getItem: (k) => store[k] || null,
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    };

    function makeJwt(payload) {
      const header = Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT" })).toString('base64url');
      const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
      return `${header}.${body}.mockSignature`;
    }

    const nowSec = Math.floor(Date.now() / 1000);
    const expiredJwt = makeJwt({
      name: "Expired User",
      preferred_username: "expired@example.com",
      exp: nowSec - 3600,
      roles: ["SYSTEM_ADMIN"],
    });

    const validJwt = makeJwt({
      name: "Valid User",
      preferred_username: "valid@example.com",
      exp: nowSec + 3600,
      roles: ["KNOWLEDGE_ADMIN"],
    });

    const results = {
      expiredIsExpired: isTokenExpired(expiredJwt),
      validIsExpired: isTokenExpired(validJwt),
      expiredDetails: getTokenExpiryDetails(expiredJwt),
      validDetails: getTokenExpiryDetails(validJwt),
    };

    saveAuthHeaders({ bearerToken: validJwt });
    const headersWithBearer = authHeaders();
    results.bearerHeader = headersWithBearer.Authorization;

    global.sessionStorage.removeItem("ai_ops_backoffice_auth");
    const fallbackHeaders = authHeaders();
    results.hasFallback = !!fallbackHeaders["X-Backoffice-Role"];

    console.log(JSON.stringify(results));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout.strip())
    assert data["expiredIsExpired"] is True
    assert data["validIsExpired"] is False
    assert data["expiredDetails"]["isExpired"] is True
    assert data["validDetails"]["isExpired"] is False
    assert data["validDetails"]["name"] == "Valid User"
    assert "Bearer " in data["bearerHeader"]
    assert data["hasFallback"] is True

