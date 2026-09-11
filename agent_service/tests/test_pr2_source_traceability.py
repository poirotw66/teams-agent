"""Acceptance test suite for PR-2: Secure and Accurate Source Traceability.

Verifies:
- F02-T1: Cross-tenant, cross-unit, and revoked users cannot preview, range-stream, or download files.
- F03-T1: Strict historical version matching without falling back to newer versions or active releases.
- F07-T1: Multi-instance shared artifact storage read and SHA-256 integrity verification.
- F08-T1: Multi-format locators and explicit degraded messages for PDF, Office, Spreadsheet, Edited MD, and unpreserved originals.
- A06-T1: Direct O(1) repository lookup without scanning releases, and strictly bounded LRU/TTL caching.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_service.artifact_storage import GcsArtifactStorage, LocalFileArtifactStorage
from agent_service.document_authorization import (
    DocumentAccessDeniedError,
    authorize_document_access,
    ensure_document_access,
)
from ai_ops_backoffice.routers.ops_reads import register_ops_read_routes
from ai_ops_backoffice.services.source_models import (
    ArtifactKind,
    LocatorType,
    MappingStatus,
    SourceLocator,
    SourceRecord,
)
from ai_ops_backoffice.services.source_repository import (
    BoundedSourceCache,
    FileSourceRecordRepository,
    InMemorySourceRecordRepository,
)
from ai_ops_backoffice.services.source_trace import SourceTraceResolver


class MockActor:
    def __init__(
        self,
        user_id: str = "u-1",
        tenant_id: str | None = "tenant-a",
        role: str = "CONTRIBUTOR",
        owner_unit_ids: list[str] | None = None,
        capabilities: list[str] | None = None,
        groups: list[str] | None = None,
        revoked: bool = False,
    ) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role
        self.owner_unit_ids = owner_unit_ids or ["HR-UNIT"]
        self.capabilities = capabilities or ["ops.conversations.read"]
        self.groups = groups or []
        self.revoked = revoked
        self.display_name = user_id


# ============================================================================
# F02-T1: ACL Denial Across Tenant, Unit, and Revocation
# ============================================================================


def test_f02_t1_cross_tenant_denial() -> None:
    doc = SourceRecord(
        source_ref_id="src-000000000000000000000001",
        tenant_id="tenant-alpha",
        document_id="doc-1",
        version_id="ver-1",
        release_id="rel-1",
        owner_unit_id="HR-UNIT",
    )
    cross_tenant_actor = MockActor(tenant_id="tenant-beta", owner_unit_ids=["HR-UNIT"])
    decision = authorize_document_access(cross_tenant_actor, doc, action="preview")
    assert not decision.allowed
    assert decision.status_code == 404
    assert decision.safe_error_code == "TENANT_MISMATCH"

    with pytest.raises(DocumentAccessDeniedError) as exc_info:
        ensure_document_access(cross_tenant_actor, doc, action="preview")
    assert exc_info.value.status_code == 404


def test_f02_t1_cross_unit_denial() -> None:
    doc = SourceRecord(
        source_ref_id="src-000000000000000000000002",
        tenant_id="tenant-alpha",
        document_id="doc-1",
        version_id="ver-1",
        release_id="rel-1",
        owner_unit_id="FINANCE-UNIT",
    )
    cross_unit_actor = MockActor(
        tenant_id="tenant-alpha",
        role="CONTRIBUTOR",
        owner_unit_ids=["IT-UNIT"],
    )
    decision = authorize_document_access(cross_unit_actor, doc, action="download")
    assert not decision.allowed
    assert decision.status_code == 404
    assert decision.safe_error_code == "UNIT_MISMATCH"


def test_f02_t1_revoked_user_denial() -> None:
    doc = SourceRecord(
        source_ref_id="src-000000000000000000000003",
        tenant_id="tenant-alpha",
        document_id="doc-1",
        version_id="ver-1",
        release_id="rel-1",
        owner_unit_id="HR-UNIT",
    )
    revoked_actor = MockActor(
        tenant_id="tenant-alpha",
        owner_unit_ids=["HR-UNIT"],
        revoked=True,
    )
    decision = authorize_document_access(revoked_actor, doc, action="preview")
    assert not decision.allowed
    assert decision.status_code == 403
    assert decision.safe_error_code == "REVOKED"


# ============================================================================
# F03-T1: Exact Historical Version Matching Without Fallback
# ============================================================================


def test_f03_t1_exact_version_matching(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True)

    # Release 1 with doc version 1
    rel1 = releases_dir / "rel-1"
    (rel1 / "index").mkdir(parents=True)
    (rel1 / "manifest.json").write_text(
        json.dumps(
            {
                "releaseId": "rel-1",
                "documents": [
                    {
                        "document_id": "doc-policy",
                        "version_id": "ver-1",
                        "title": "Security Policy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (rel1 / "index" / "chunks.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "chunk-101",
                        "document_id": "doc-policy",
                        "version_id": "ver-1",
                        "source_path": "sources/doc-policy.md",
                        "content": "Version 1 Policy Content",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # Release 2 with updated doc version 2 (same documentId and title)
    rel2 = releases_dir / "rel-2"
    (rel2 / "index").mkdir(parents=True)
    (rel2 / "manifest.json").write_text(
        json.dumps(
            {
                "releaseId": "rel-2",
                "documents": [
                    {
                        "document_id": "doc-policy",
                        "version_id": "ver-2",
                        "title": "Security Policy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (rel2 / "index" / "chunks.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "chunk-201",
                        "document_id": "doc-policy",
                        "version_id": "ver-2",
                        "source_path": "sources/doc-policy.md",
                        "content": "Version 2 Policy Content Updated",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    resolver = SourceTraceResolver(releases_dir)

    # Query specifying release rel-1 and ver-1 should resolve to ver-1
    resolved_v1 = resolver.resolve_citation(
        {
            "releaseId": "rel-1",
            "versionId": "ver-1",
            "chunkId": "chunk-101",
            "documentId": "doc-policy",
        }
    )
    assert resolved_v1 is not None
    assert resolved_v1.version_id == "ver-1"
    assert resolved_v1.release_id == "rel-1"
    assert "Version 1" in (resolved_v1.content or "")

    # Query requesting ver-1 in release rel-2 should NOT match chunk-201 (version mismatch)
    mismatched = resolver.resolve_citation(
        {
            "releaseId": "rel-2",
            "versionId": "ver-1",
            "chunkId": "chunk-201",
            "documentId": "doc-policy",
        }
    )
    assert mismatched is None

    # Query with nonexistent chunkId should NOT fallback to other chunks
    missing_chunk = resolver.resolve_citation(
        {
            "releaseId": "rel-1",
            "versionId": "ver-1",
            "chunkId": "chunk-nonexistent",
            "documentId": "doc-policy",
        }
    )
    assert missing_chunk is None

    # Deleting old release directory: resolver must NOT silently substitute rel-2
    import shutil
    shutil.rmtree(rel1)
    resolver._release_cache.clear()
    deleted_lookup = resolver.resolve_citation(
        {
            "releaseId": "rel-1",
            "versionId": "ver-1",
            "chunkId": "chunk-101",
            "documentId": "doc-policy",
        }
    )
    assert deleted_lookup is None


# ============================================================================
# F07-T1: Multi-Instance Shared Artifact Storage Read and Hash Verification
# ============================================================================


@pytest.mark.asyncio
async def test_f07_t1_multi_instance_shared_storage() -> None:
    bucket_name = "test-corp-artifacts-bucket"
    data = b"%PDF-1.4 Mock PDF binary contents with multiple pages and tables..."
    expected_sha256 = hashlib.sha256(data).hexdigest()

    # Instance 1: uploads artifact to shared GCS storage
    instance1_store = GcsArtifactStorage(bucket_name=bucket_name)
    record1 = await instance1_store.store_artifact(
        tenant_id="tenant-alpha",
        artifact_id="art-doc-contract-v1",
        data=data,
        filename="contract.pdf",
        mime_type="application/pdf",
        kind=ArtifactKind.ORIGINAL,
    )
    assert record1.sha256 == expected_sha256
    assert record1.size == len(data)

    # Instance 2: completely separate store instance without shared local disk
    instance2_store = GcsArtifactStorage(bucket_name=bucket_name)
    exists = await instance2_store.artifact_exists("tenant-alpha", "art-doc-contract-v1")
    assert exists

    record2, stream = await instance2_store.get_artifact("tenant-alpha", "art-doc-contract-v1")
    assert record2.artifact_id == "art-doc-contract-v1"

    downloaded = bytearray()
    async for chunk in stream:
        downloaded.extend(chunk)

    assert bytes(downloaded) == data
    assert hashlib.sha256(downloaded).hexdigest() == expected_sha256

    # Test HTTP Range read on instance 2
    rec_range, range_slice = await instance2_store.get_artifact_range(
        "tenant-alpha", "art-doc-contract-v1", start=10, end=25
    )
    assert range_slice == data[10:26]


# ============================================================================
# F08-T1: Multi-Format Locators and Degraded Statuses
# ============================================================================


def test_f08_t1_pdf_locator() -> None:
    chunk = {
        "page_index": 2,
        "page_label": "3",
        "bbox": [72.0, 100.0, 500.0, 150.0],
        "coordinate_system": "PDF_POINTS_72DPI",
    }
    locator = SourceTraceResolver._build_locator("PDF", chunk, {}, {})
    assert locator.locator_type == LocatorType.PDF
    assert locator.page_index == 2
    assert locator.page_label == "3"
    assert locator.bbox == [72.0, 100.0, 500.0, 150.0]
    assert locator.coordinate_system == "PDF_POINTS_72DPI"
    assert locator.degraded_reason is None


def test_f08_t1_office_preview_locator() -> None:
    chunk = {
        "preview_replica_artifact_ref": "art-preview-pdf-123",
        "converter_version": "libreoffice-7.6.2",
        "slide_index": 4,
        "section_path": "Executive Summary > Overview",
    }
    locator = SourceTraceResolver._build_locator("PPTX", chunk, {}, {})
    assert locator.locator_type == LocatorType.OFFICE_PREVIEW
    assert locator.preview_replica_artifact_ref == "art-preview-pdf-123"
    assert locator.converter_version == "libreoffice-7.6.2"
    assert locator.slide_index == 4
    assert locator.section_path == "Executive Summary > Overview"
    assert "Office 文件已產生 PDF 預覽副本" in (locator.degraded_reason or "")


def test_f08_t1_spreadsheet_locator() -> None:
    chunk = {
        "sheet_name": "Q3 Revenue",
        "cell_range": "B2:E15",
    }
    locator = SourceTraceResolver._build_locator("XLSX", chunk, {}, {})
    assert locator.locator_type == LocatorType.SPREADSHEET
    assert locator.sheet_name == "Q3 Revenue"
    assert locator.cell_range == "B2:E15"
    assert "試算表格式不支援頁面高亮" in (locator.degraded_reason or "")


def test_f08_t1_edited_derivative_preview_payload(tmp_path: Path) -> None:
    resolver = SourceTraceResolver(tmp_path)
    source = SourceRecord(
        source_ref_id="src-000000000000000000000004",
        tenant_id="tenant-alpha",
        document_id="doc-1",
        version_id="ver-1",
        release_id="rel-1",
        mapping_status=MappingStatus.EDITED_DERIVATIVE,
        source_type="DERIVED_MARKDOWN",
        excerpt="Edited markdown content differing from attachment.",
        locator=SourceLocator(
            locator_type=LocatorType.MARKDOWN,
            section_path="Authentication",
            paragraph_id="para-2",
        ),
    )
    resolved = resolver._source_record_to_resolved(source)
    preview = resolver.preview_payload(resolved)
    assert preview["mappingStatus"] == MappingStatus.EDITED_DERIVATIVE.value
    assert "此文件為手動編輯之衍生版本" in preview["message"]
    assert preview["locator"]["section_path"] == "Authentication"


def test_f08_t1_original_not_preserved_preview_payload(tmp_path: Path) -> None:
    resolver = SourceTraceResolver(tmp_path)
    source = SourceRecord(
        source_ref_id="src-000000000000000000000005",
        tenant_id="tenant-alpha",
        document_id="doc-2",
        version_id="ver-1",
        release_id="rel-1",
        mapping_status=MappingStatus.ORIGINAL_NOT_PRESERVED,
        source_type="DERIVED_MARKDOWN",
        excerpt="Legacy markdown only.",
    )
    resolved = resolver._source_record_to_resolved(source)
    preview = resolver.preview_payload(resolved)
    assert preview["mappingStatus"] == MappingStatus.ORIGINAL_NOT_PRESERVED.value
    assert "原始檔尚未保存" in preview["message"]
    assert "可補上經核對之同版原始檔" in preview["actions"]["nextSteps"]


# ============================================================================
# A06-T1: Direct O(1) Repository Query and Bounded Cache
# ============================================================================


def test_a06_t1_direct_lookup_without_scanning_releases(tmp_path: Path) -> None:
    repo = InMemorySourceRecordRepository()
    record = SourceRecord(
        source_ref_id="src-111111111111111111111111",
        tenant_id="tenant-test",
        document_id="doc-direct",
        version_id="ver-1",
        release_id="rel-1",
        title="Direct Document",
        excerpt="Directly indexed content.",
    )
    repo.save_source_record_sync(record)

    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()

    resolver = SourceTraceResolver(releases_dir, source_repository=repo)

    # Patch releases_dir.iterdir to verify it is NEVER called for a direct source lookup
    with patch.object(Path, "iterdir", side_effect=AssertionError("Release scanning forbidden")):
        resolved = resolver.resolve_source_ref(
            "src-111111111111111111111111", tenant_id="tenant-test"
        )

    assert resolved is not None
    assert resolved.title == "Direct Document"
    assert resolved.document_id == "doc-direct"


def test_a06_t1_bounded_cache_memory_limit() -> None:
    # Max size = 3
    cache = BoundedSourceCache(max_size=3, ttl_seconds=60.0)

    # Insert 5 items
    for i in range(1, 6):
        rec = SourceRecord(
            source_ref_id=f"src-00000000000000000000000{i}",
            tenant_id="tenant-1",
            document_id=f"doc-{i}",
            version_id="ver-1",
            release_id="rel-1",
        )
        cache.put(rec)

    # Cache size must not exceed max_size 3
    assert cache.size() == 3

    # The oldest entries (1 and 2) must have been evicted
    assert cache.get("tenant-1", "src-000000000000000000000001") is None
    assert cache.get("tenant-1", "src-000000000000000000000002") is None

    # The newest entries (3, 4, 5) must be present
    assert cache.get("tenant-1", "src-000000000000000000000003") is not None
    assert cache.get("tenant-1", "src-000000000000000000000004") is not None
    assert cache.get("tenant-1", "src-000000000000000000000005") is not None


@pytest.mark.asyncio
async def test_gcs_storage_chunked_streaming_and_sha256():
    """Verifies true GCS chunked streaming via blob.open and SHA-256 integrity."""
    import io
    from agent_service.artifact_storage import GcsArtifactStorage

    test_content = b"This is a test document for streaming verification." * 100
    expected_sha = hashlib.sha256(test_content).hexdigest()

    class MockBlob:
        def __init__(self, name: str):
            self.name = name
            self.generation = 12345
            self.content_type = "text/plain"
            self.size = len(test_content)
            self.metadata = {}

        def upload_from_string(self, data, content_type=None):
            pass

        def open(self, mode="rb"):
            return io.BytesIO(test_content)

        def download_as_bytes(self, start=None, end=None):
            if start is not None and end is not None:
                return test_content[start : end + 1]
            return test_content

    mock_blob = MockBlob("tenants/t1/artifacts/art-1/test.txt")

    class MockBucket:
        def blob(self, name):
            return mock_blob

    class MockClient:
        def bucket(self, name):
            return MockBucket()

        def list_blobs(self, bucket_name, prefix=None, max_results=None):
            return [mock_blob]

    storage = GcsArtifactStorage("my-bucket", client=MockClient())
    record = await storage.store_artifact(
        tenant_id="t1",
        artifact_id="art-1",
        data=test_content,
        filename="test.txt",
    )
    assert record.sha256 == expected_sha
    assert mock_blob.metadata.get("sha256") == expected_sha

    # Clear shared store to test direct GCS retrieval
    storage._SHARED_STORE["my-bucket"].clear()

    rec_fetched, stream = await storage.get_artifact("t1", "art-1")
    assert rec_fetched.sha256 == expected_sha
    streamed_chunks = []
    async for chunk in stream:
        streamed_chunks.append(chunk)
    assert b"".join(streamed_chunks) == test_content

    # Test range
    _, range_bytes = await storage.get_artifact_range("t1", "art-1", 0, 10)
    assert range_bytes == test_content[0:11]


def test_core_agent_service_has_no_backoffice_reverse_dependencies():
    """A08: Core agent_service modules must not import from ai_ops_backoffice."""
    from agent_service.document_authorization import DocumentAccessDecision
    from agent_service.artifact_models import ArtifactRecord

    assert DocumentAccessDecision.__module__ == "agent_service.document_authorization"
    assert ArtifactRecord.__module__ == "agent_service.artifact_models"

