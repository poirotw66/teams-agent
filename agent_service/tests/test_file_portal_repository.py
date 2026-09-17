import json
from datetime import UTC, datetime

import pytest

from knowledge_portal.file_repository import FilePortalRepository
from knowledge_portal.models import KnowledgeDocumentRecord, KnowledgeVersionRecord


@pytest.mark.asyncio
async def test_repository_loads_legacy_archived_document_as_unpublished(tmp_path) -> None:
    state_path = tmp_path / "portal-state.json"
    document = KnowledgeDocumentRecord(
        document_id="doc-legacy",
        title="Legacy guide",
        owner_unit_id="IT Service Desk",
        current_published_version_id="ver-legacy-1",
        status="DRAFT",
        etag='W/"doc-legacy-1"',
        created_at=datetime.now(UTC),
        created_by="test-user",
        updated_at=datetime.now(UTC),
        updated_by="test-user",
    )
    legacy_document = document.model_dump(mode="json")
    legacy_document["status"] = "ARCHIVED"
    state_path.write_text(
        json.dumps({"documents": [legacy_document]}),
        encoding="utf-8",
    )

    repository = FilePortalRepository(state_path)

    loaded = await repository.get_document("doc-legacy")

    assert loaded is not None
    assert loaded.status == "UNPUBLISHED"


@pytest.mark.asyncio
async def test_repository_normalizes_legacy_uploaded_version(tmp_path) -> None:
    state_path = tmp_path / "portal-state.json"
    version = KnowledgeVersionRecord(
        version_id="ver-legacy-1",
        document_id="doc-legacy",
        version_number=1,
        source_type="PDF",
        content_hash="content-hash",
        canonical_content="# Legacy guide",
        effective_at="2026-09-17",
        review_due_at="2027-09-17",
        owner_unit_id="IT Service Desk",
        title="Legacy guide",
        etag='W/"ver-legacy-1"',
        created_at=datetime.now(UTC),
        created_by="test-user",
    )
    legacy_version = version.model_dump(mode="json")
    legacy_version["source_type"] = "PDF_UPLOAD"
    legacy_version.pop("etag")
    state_path.write_text(
        json.dumps({"versions": [legacy_version]}),
        encoding="utf-8",
    )

    repository = FilePortalRepository(state_path)

    loaded = await repository.get_version("ver-legacy-1")

    assert loaded is not None
    assert loaded.source_type == "PDF"
    assert loaded.etag == 'W/"ver-legacy-1"'
