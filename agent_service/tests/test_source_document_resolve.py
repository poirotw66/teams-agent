"""SourceRecord resolve-by-document and quality content fallback coverage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from test_ai_ops_backoffice import _seed_sample_events

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.services.source_models import MappingStatus, SourceRecord
from ai_ops_backoffice.services.source_repository import prefer_document_source_record
from ai_ops_backoffice.settings import BackofficeSettings


def _settings(tmp_path: Path) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    asyncio.run(_seed_sample_events(store_path, data_dir))
    return BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="FILE",
        ops_store_path=store_path,
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="FILE",
        knowledge_portal_url="http://knowledge-portal.invalid",
        knowledge_internal_url="http://knowledge-portal.invalid",
        knowledge_service_token="",
        knowledge_delegation_secret="",
        knowledge_bridge_enabled=False,
        deployment_tenant_id="local-development",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        governance_store_path=tmp_path / "governance.json",
        source_store_mode="FILE",
        source_store_path=tmp_path / "sources",
    )


def _headers() -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": "ops.admin",
        "X-Backoffice-User-Name": "Ops Admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_prefer_document_source_record_prefers_document_level() -> None:
    chunk = SourceRecord(
        source_ref_id="src-aaaaaaaaaaaaaaaaaaaaaaaa",
        tenant_id="local-development",
        document_id="doc-1",
        version_id="ver-1",
        release_id="rel-1",
        chunk_id="chunk-1",
        mapping_status=MappingStatus.AVAILABLE,
    )
    document = SourceRecord(
        source_ref_id="src-bbbbbbbbbbbbbbbbbbbbbbbb",
        tenant_id="local-development",
        document_id="doc-1",
        version_id="ver-1",
        release_id="rel-1",
        chunk_id=None,
        mapping_status=MappingStatus.AVAILABLE,
    )
    preferred = prefer_document_source_record([chunk, document])
    assert preferred is not None
    assert preferred.source_ref_id == document.source_ref_id


def test_resolve_sources_by_document_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    repo = app.state.query_service._source_trace.source_repository
    record = SourceRecord(
        source_ref_id="src-cccccccccccccccccccccccc",
        tenant_id="local-development",
        document_id="doc-799a9a1efdb1",
        version_id="ver-82c6c035b089",
        release_id="release-19072ac9a1e2",
        mapping_status=MappingStatus.AVAILABLE,
        owner_unit_id="IT Service Desk",
        title="Portal E2E",
        artifact_ref="art-doc-799a9a1efdb1-ver-82c6c035b089",
        original_asset_name="sample.pdf",
    )
    asyncio.run(repo.save_source_record(record))

    response = client.get(
        "/api/sources",
        params={"documentId": "doc-799a9a1efdb1"},
        headers=_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sourceRefId"] == record.source_ref_id
    assert payload["documentId"] == "doc-799a9a1efdb1"
    assert payload["downloadUrl"] == f"/api/sources/{record.source_ref_id}/file"


def test_link_quality_case_content_falls_back_to_source_record(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    headers = _headers()
    repo = app.state.query_service._source_trace.source_repository
    record = SourceRecord(
        source_ref_id="src-dddddddddddddddddddddddd",
        tenant_id="local-development",
        document_id="doc-799a9a1efdb1",
        version_id="ver-82c6c035b089",
        release_id="release-19072ac9a1e2",
        mapping_status=MappingStatus.AVAILABLE,
        owner_unit_id="IT Service Desk",
    )
    asyncio.run(repo.save_source_record(record))

    refreshed = client.post(
        "/api/quality-candidates/refresh",
        headers=headers,
        json={"days": 30},
    ).json()
    candidate = next(item for item in refreshed["items"] if item["issue_type_id"])
    quality_case = client.post(
        "/api/quality-candidates/merge",
        headers=headers,
        json={
            "candidate_ids": [candidate["candidate_id"]],
            "title": "SourceRecord content link",
            "description": "Link via shared source contract without Portal inventory",
            "priority": "HIGH",
        },
    ).json()["case"]

    link_res = client.post(
        f"/api/quality-cases/{quality_case['case_id']}/content",
        headers=headers,
        json={
            "expected_etag": quality_case["etag"],
            "document_id": "doc-799a9a1efdb1",
        },
    )
    assert link_res.status_code == 200
    assert "doc-799a9a1efdb1" in link_res.json()["case"]["document_ids"]
