from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.documents import DocumentChunk
from agent_service.knowledge_release import release_index_path
from agent_service.retrieval import HybridIndex
from agent_service.settings import RagSettings
from knowledge_portal.models import (
    CreateDocumentRequest,
    PortalActor,
    PublishRequest,
    ReviewDecisionRequest,
    SubmitReviewRequest,
)
from knowledge_portal.repository import build_repository
from knowledge_portal.service import PortalService
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


def test_admin_reload_knowledge_auth_and_runtime_update(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    releases_dir = tmp_path / "releases"
    bundled_index_path = data_dir / "index" / "chunks.json"

    initial_chunks = [
        {"chunk_id": "c1", "source_path": "doc1.md", "title": "Doc 1", "content": "Initial doc content"}
    ]
    _create_test_index(bundled_index_path, initial_chunks)

    settings = RagSettings(
        data_dir=data_dir,
        index_path=bundled_index_path,
        auto_build_index=False,
        knowledge_release_mode="AUTO",
        knowledge_release_dir=releases_dir,
        service_token="secret-token-123",
        model=None,
        agent_model=None,
        embedding_model=None,
    )

    app = create_app(settings)
    with TestClient(app) as client:
        # 1. Without auth token -> 401
        resp = client.post("/admin/reload-knowledge", json={})
        assert resp.status_code == 401

        # 2. Readyz initially shows bundled index
        ready = client.get("/readyz").json()
        assert ready["chunks"] == 1
        assert ready["knowledgeReleaseId"] is None

        # 3. Create release-101 index with 2 chunks
        release_101_path = release_index_path(releases_dir, "release-101")
        new_chunks = [
            {"chunk_id": "c1", "source_path": "doc1.md", "title": "Doc 1", "content": "Updated doc 1"},
            {"chunk_id": "c2", "source_path": "doc2.md", "title": "Doc 2", "content": "Brand new doc 2"},
        ]
        _create_test_index(release_101_path, new_chunks)

        # 4. Reload knowledge with releaseId
        reload_resp = client.post(
            "/admin/reload-knowledge",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"releaseId": "release-101"},
        )
        assert reload_resp.status_code == 200
        reload_data = reload_resp.json()
        assert reload_data["status"] == "reloaded"
        assert reload_data["releaseId"] == "release-101"
        assert reload_data["chunks"] == 2

        # 5. Readyz now reports release-101 and 2 chunks
        ready_after = client.get("/readyz").json()
        assert ready_after["chunks"] == 2
        assert ready_after["knowledgeReleaseId"] == "release-101"

        # 6. Search reflects new content
        search_resp = client.post(
            "/retrieval/search",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"query": "Brand new doc 2", "limit": 2},
        )
        assert search_resp.status_code == 200
        hits = search_resp.json()["hits"]
        assert len(hits) > 0
        assert hits[0]["title"] == "Doc 2"

        # 7. 404 for non-existent release
        err_resp = client.post(
            "/admin/reload-knowledge",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"releaseId": "release-nonexistent"},
        )
        assert err_resp.status_code == 404


@pytest.mark.asyncio
async def test_portal_release_agent_sync_three_state_machine(tmp_path: Path) -> None:
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

    service = PortalService(settings, build_repository(settings))

    manager = PortalActor(
        user_id="mgr-1",
        display_name="Knowledge Manager",
        role="MANAGER",
        owner_unit_ids=["UNIT-A"],
    )

    # 1. Create document, submit review, approve
    create_req = CreateDocumentRequest(
        title="Agent Sync Document",
        summary="Testing agent sync",
        category="Policy",
        owner_unit_id="UNIT-A",
        effective_at="2026-09-01",
        review_due_at="2027-09-01",
        change_reason="Initial creation",
        markdown_content="# Agent Sync\n\nContent for testing release notification.",
    )
    detail = await service.create_document(manager, create_req, correlation_id="c-1")
    doc_id = detail.document.document_id
    draft_v_id = detail.draft_version.version_id

    await service.submit_for_review(
        manager,
        doc_id,
        SubmitReviewRequest(etag=detail.document.etag, change_reason="Ready for review"),
        correlation_id="c-2",
    )
    pending = await service.list_pending_reviews(manager)
    review_id = next(item.review_id for item in pending.items if item.document_id == doc_id)

    await service.decide_review(
        manager,
        review_id,
        ReviewDecisionRequest(decision="APPROVED", comment="Looks great"),
        correlation_id="c-3",
    )

    # 2. Simulate agent notification failure on publish -> status should be RELOAD_FAILED
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = httpx.Response(status_code=500, text="Agent internal error", request=httpx.Request("POST", "http://agent-test-service:8000/admin/reload-knowledge"))
        mock_post.return_value = mock_resp

        rel_record = await service.publish_version(
            manager,
            doc_id,
            PublishRequest(version_id=draft_v_id, reason="First publish"),
            correlation_id="c-4",
        )
        assert rel_record.status == "RELOAD_FAILED"
        assert "Agent reload returned HTTP 500" in rel_record.failure_summary
        assert rel_record.verified_at is None

    # 3. Retry sync with agent -> succeeds -> status transitions to ACTIVE
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = httpx.Response(
            status_code=200,
            json={"status": "reloaded", "releaseId": rel_record.release_id, "chunks": 1},
            request=httpx.Request("POST", "http://agent-test-service:8000/admin/reload-knowledge"),
        )
        mock_post.return_value = mock_resp

        synced = await service.sync_agent_release(
            manager,
            rel_record.release_id,
            correlation_id="c-5",
        )
        assert synced.status == "ACTIVE"
        assert synced.verified_at is not None
        assert synced.failure_summary == ""

    # 4. Rollback release also triggers agent reload
    from knowledge_portal.models import RollbackRequest
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = httpx.Response(
            status_code=200,
            json={"status": "reloaded", "releaseId": rel_record.release_id, "chunks": 1},
            request=httpx.Request("POST", "http://agent-test-service:8000/admin/reload-knowledge"),
        )
        mock_post.return_value = mock_resp

        rolled = await service.rollback_release(
            manager,
            RollbackRequest(release_id=rel_record.release_id, reason="Testing rollback sync"),
            correlation_id="c-6",
        )
        assert rolled.status == "ACTIVE"
        assert rolled.verified_at is not None

