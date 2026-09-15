"""End-to-end automated test suite for Console V2 Quality Case closed loop and SPA serving."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from test_ai_ops_backoffice import _seed_sample_events

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.settings import PortalSettings

SECRET = "test-console-v2-closed-loop-secret"


def _portal_settings(tmp_path: Path) -> PortalSettings:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "data_dir", tmp_path)
    object.__setattr__(settings, "drafts_dir", tmp_path / "drafts")
    object.__setattr__(settings, "require_dual_approval", False)
    object.__setattr__(settings, "relaxed_workflow", True)
    object.__setattr__(settings, "embedding_model", None)
    object.__setattr__(settings, "delegation_secret", SECRET)
    object.__setattr__(settings, "require_service_token_with_delegation", False)
    return settings


def _backoffice_settings(tmp_path: Path, *, console_v2_enabled: bool = True) -> BackofficeSettings:
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
        knowledge_portal_url="http://knowledge-portal.test",
        knowledge_internal_url="http://knowledge-portal.test",
        knowledge_service_token="",
        knowledge_delegation_secret=SECRET,
        knowledge_bridge_enabled=True,
        deployment_tenant_id="local-development",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        governance_store_path=tmp_path / "governance.json",
        quality_store_mode="FILE",
        quality_store_path=tmp_path / "quality.json",
        console_v2_enabled=console_v2_enabled,
    )


def _auth_headers(role: str = "KNOWLEDGE_ADMIN", user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_console_v2_spa_and_static_serving(tmp_path: Path) -> None:
    settings = _backoffice_settings(tmp_path, console_v2_enabled=True)
    app = create_app(settings)
    client = TestClient(app)

    # 1. Root console-v2 URL serves index.html with no-cache headers
    res_root = client.get("/console-v2/")
    assert res_root.status_code == 200
    assert '<div id="root">' in res_root.text
    assert "no-cache, must-revalidate" in res_root.headers.get("cache-control", "")

    # 2. Deep links fall back to SPA index.html
    res_work = client.get("/console-v2/work")
    assert res_work.status_code == 200
    assert '<div id="root">' in res_work.text

    res_case = client.get("/console-v2/improvements/cases/case-test-123")
    assert res_case.status_code == 200
    assert '<div id="root">' in res_case.text

    # 3. Static JS asset serves file correctly
    res_asset = client.get("/console-v2/assets/index-B7P6jG0d.js")
    assert res_asset.status_code == 200
    assert len(res_asset.content) > 1000


def test_quality_case_end_to_end_closed_loop(tmp_path: Path) -> None:
    portal_app = create_portal_app(_portal_settings(tmp_path))
    transport = httpx.ASGITransport(app=portal_app)

    settings = _backoffice_settings(tmp_path, console_v2_enabled=True)
    app = create_app(settings, knowledge_transport=transport)
    client = TestClient(app)

    admin_headers = _auth_headers("KNOWLEDGE_ADMIN")
    owner_headers = _auth_headers("SERVICE_OWNER")

    # Step 1: Ingestion & Merge
    refresh_res = client.post("/api/quality-candidates/refresh", headers=admin_headers, json={"days": 30})
    assert refresh_res.status_code == 200
    candidate = next(item for item in refresh_res.json()["items"] if item["issue_type_id"])
    candidate_id = candidate["candidate_id"]

    merge_res = client.post(
        "/api/quality-candidates/merge",
        headers=admin_headers,
        json={
            "candidate_ids": [candidate_id],
            "title": "VPN 連線異常排查與指引改善",
            "description": "提供使用者完整的 VPN 連線障礙排除步驟。",
            "priority": "HIGH",
        },
    )
    assert merge_res.status_code == 200
    case = merge_res.json()["case"]
    case_id = case["case_id"]
    assert case["status"] == "NEW"
    etag = case["etag"]

    # Verify initial workflow stage (triage is current)
    wf_res1 = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=admin_headers)
    assert wf_res1.status_code == 200
    wf1 = wf_res1.json()
    assert len(wf1["stages"]) == 5
    assert wf1["stages"][0]["id"] == "triage"
    assert wf1["stages"][0]["status"] == "current"
    assert "triage" in wf1["allowed_actions"]
    assert any(e["source_type"] == "quality_candidate" for e in wf1["evidence_refs"])

    # Step 2: Triage
    triage_res = client.post(
        f"/api/quality-cases/{case_id}/transition",
        headers=admin_headers,
        json={"status": "TRIAGED", "reason": "確認為知識庫文件缺漏問題", "expected_etag": etag},
    )
    assert triage_res.status_code == 200
    case = triage_res.json()["case"]
    assert case["status"] == "TRIAGED"
    etag = case["etag"]

    wf_res2 = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=admin_headers)
    wf2 = wf_res2.json()
    assert wf2["stages"][0]["status"] == "completed"
    assert "create_document_draft" in wf2["allowed_actions"]

    # Step 3: Create document draft & link content
    draft_res = client.post(
        f"/api/quality-cases/{case_id}/document-draft",
        headers=admin_headers,
        json={
            "expected_case_etag": etag,
            "title": "VPN 連線障礙排除指南",
            "summary": "由品質案件自動建立之 VPN 改善文件草稿",
            "markdown_content": "# VPN 障礙排除指引\n\n1. 重新啟動 VPN 客戶端\n2. 檢查雙重驗證",
        },
    )
    assert draft_res.status_code == 200
    draft_data = draft_res.json()
    assert draft_data["partialSuccess"] is False
    doc_id = draft_data["document"]["document_id"]
    case = draft_data["case"]
    assert doc_id in case["document_ids"]
    etag = case["etag"]

    # Advance to IN_PROGRESS
    prog_res = client.post(
        f"/api/quality-cases/{case_id}/transition",
        headers=admin_headers,
        json={"status": "IN_PROGRESS", "reason": "展開內容修正與撰寫", "expected_etag": etag},
    )
    assert prog_res.status_code == 200
    case = prog_res.json()["case"]
    etag = case["etag"]

    wf_res3 = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=admin_headers)
    wf3 = wf_res3.json()
    assert wf3["stages"][1]["id"] == "fix_content"
    assert wf3["stages"][1]["status"] == "current"
    assert any(e["source_type"] == "document_draft" and e["source_id"] == doc_id for e in wf3["evidence_refs"])

    # Step 4: Verification Review
    review_res = client.post(
        f"/api/quality-cases/{case_id}/transition",
        headers=admin_headers,
        json={"status": "WAITING_REVIEW", "reason": "文件草稿撰寫完畢，送交雙重審核", "expected_etag": etag},
    )
    assert review_res.status_code == 200
    case = review_res.json()["case"]
    etag = case["etag"]

    wf_res4 = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=admin_headers)
    wf4 = wf_res4.json()
    assert wf4["stages"][1]["status"] == "completed"
    assert wf4["stages"][2]["id"] == "verification_review"
    assert wf4["stages"][2]["status"] == "current"
    assert "start_observation" in wf4["allowed_actions"]

    # Step 5: Transition to Observing
    obs_res = client.post(
        f"/api/quality-cases/{case_id}/transition",
        headers=admin_headers,
        json={"status": "OBSERVING", "reason": "審核通過，文件已發布，進入線上成效觀察期", "expected_etag": etag},
    )
    assert obs_res.status_code == 200
    case = obs_res.json()["case"]
    assert case["status"] == "OBSERVING"
    assert case["observation_started_at"] is not None
    etag = case["etag"]

    wf_res5 = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=admin_headers)
    wf5 = wf_res5.json()
    assert wf5["stages"][2]["status"] == "completed"
    assert wf5["stages"][3]["id"] == "observation"
    assert wf5["stages"][3]["status"] == "current"
    assert "refresh_observation" in wf5["allowed_actions"]

    # Step 6: Refresh Observation Metrics
    refresh_obs_res = client.post(
        f"/api/quality-cases/{case_id}/observation/refresh",
        headers=admin_headers,
        json={"expected_etag": etag},
    )
    assert refresh_obs_res.status_code == 200
    case = refresh_obs_res.json()["case"]
    assert case["observation_latest"] is not None
    etag = case["etag"]

    wf_res6 = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=admin_headers)
    wf6 = wf_res6.json()
    assert any(e["source_type"] == "observation_metric" for e in wf6["evidence_refs"])

    # Step 7: Optimistic locking conflict protection (409)
    conflict_res = client.post(
        f"/api/quality-cases/{case_id}/transition",
        headers=owner_headers,
        json={"status": "RESOLVED", "reason": "舊版 etag 測試", "resolution_type": "DOCUMENT_UPDATED", "expected_etag": 1},
    )
    assert conflict_res.status_code == 409

    # Step 8: RBAC check - KNOWLEDGE_ADMIN lacks ops.quality.resolve
    forbidden_res = client.post(
        f"/api/quality-cases/{case_id}/transition",
        headers=admin_headers,
        json={"status": "RESOLVED", "reason": "結案測試", "resolution_type": "DOCUMENT_UPDATED", "expected_etag": etag},
    )
    assert forbidden_res.status_code == 403

    # Step 9: Resolve Case by SERVICE_OWNER
    resolve_res = client.post(
        f"/api/quality-cases/{case_id}/transition",
        headers=owner_headers,
        json={
            "status": "RESOLVED",
            "resolution_type": "DOCUMENT_UPDATED",
            "reason": "VPN 連線文件已更新上線，線上負向回饋歸零，觀察指標穩定，驗收結案。",
            "expected_etag": etag,
        },
    )
    assert resolve_res.status_code == 200
    case = resolve_res.json()["case"]
    assert case["status"] == "RESOLVED"
    assert case["resolution_type"] == "DOCUMENT_UPDATED"

    # Verify final workflow state: all 5 stages completed, all evidence refs intact
    wf_final_res = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=owner_headers)
    assert wf_final_res.status_code == 200
    wf_final = wf_final_res.json()
    assert wf_final["status"] == "RESOLVED"
    for stage in wf_final["stages"]:
        assert stage["status"] == "completed"

    evidence_sources = {e["source_type"] for e in wf_final["evidence_refs"]}
    assert "quality_candidate" in evidence_sources
    assert "document_draft" in evidence_sources
    assert "observation_metric" in evidence_sources
