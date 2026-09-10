from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings


def _test_settings(tmp_path: Path) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    return BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="FILE",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        governance_store_path=tmp_path / "governance.json",
        eval_store_mode="FILE",
        eval_store_path=tmp_path / "golden_evals.json",
        quality_store_mode="FILE",
        quality_store_path=tmp_path / "quality.json",
    )


def auth_headers(role: str, user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk,HR",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_evaluations_api_full_flow(tmp_path: Path):
    app = create_app(_test_settings(tmp_path))
    client = TestClient(app)

    kadmin = auth_headers("KNOWLEDGE_ADMIN", "author_kadmin")
    sowner = auth_headers("SERVICE_OWNER", "reviewer_sowner")

    # 1. Create a case
    create_res = client.post(
        "/api/evaluations/cases",
        json={
            "title": "VPN 設定指引",
            "query": "如何在 Mac 上設定公司的 VPN 連線？",
            "owner_unit_id": "IT Service Desk",
            "behavior": "ANSWER_WITH_CITATION",
            "reference_answer": "請下載 GlobalProtect 用戶端並登入 vpn.example.com",
            "required_facts": [{"criterion_id": "c1", "description": "使用 GlobalProtect 用戶端"}],
            "forbidden_claims": ["使用 PPTP 連線"],
            "tags": ["network", "vpn"],
            "criticality": "NORMAL",
            "source_type": "FAQ",
            "source_id": "faq_vpn_01",
        },
        headers=kadmin,
    )
    assert create_res.status_code == 201, create_res.text
    case_data = create_res.json()["case"]
    rev_data = create_res.json()["revision"]
    case_id = case_data["case_id"]
    rev_id = rev_data["revision_id"]

    # 2. List cases
    list_res = client.get("/api/evaluations/cases?q=VPN", headers=kadmin)
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1

    # 3. Get case detail
    detail_res = client.get(f"/api/evaluations/cases/{case_id}", headers=kadmin)
    assert detail_res.status_code == 200
    assert detail_res.json()["case"]["case_id"] == case_id

    # 4. Submit revision for review
    submit_res = client.post(
        f"/api/evaluations/cases/{case_id}/revisions/{rev_id}/submit",
        json={"expected_etag": rev_data["etag"]},
        headers=kadmin,
    )
    assert submit_res.status_code == 200
    assert submit_res.json()["revision"]["status"] == "IN_REVIEW"

    # 5. Review revision: self-approval blocked
    self_appr = client.post(
        f"/api/evaluations/cases/{case_id}/revisions/{rev_id}/review",
        json={"approve": True, "reason": "Self-approval", "expected_etag": submit_res.json()["revision"]["etag"]},
        headers=kadmin,  # Author!
    )
    assert self_appr.status_code == 403

    # Independent review approved
    review_res = client.post(
        f"/api/evaluations/cases/{case_id}/revisions/{rev_id}/review",
        json={"approve": True, "reason": "Verified steps and client name", "expected_etag": submit_res.json()["revision"]["etag"]},
        headers=sowner,  # Independent Service Owner!
    )
    assert review_res.status_code == 200
    assert review_res.json()["revision"]["status"] == "APPROVED"

    # 6. Create Eval Set
    set_res = client.post(
        "/api/evaluations/sets",
        json={
            "name": "IT 基礎網路驗收集",
            "owner_unit_ids": ["IT Service Desk"],
            "purpose": "DEVELOPMENT",
            "description": "涵蓋 VPN、Wi-Fi、DNS 相關驗收問題",
        },
        headers=kadmin,
    )
    assert set_res.status_code == 201
    set_id = set_res.json()["eval_set"]["set_id"]

    # 7. Create draft set version and publish
    draft_res = client.post(
        f"/api/evaluations/sets/{set_id}/versions",
        json={"case_revision_ids": [rev_id]},
        headers=kadmin,
    )
    assert draft_res.status_code == 201
    version_id = draft_res.json()["version"]["set_version_id"]

    pub_res = client.post(
        f"/api/evaluations/sets/{set_id}/versions/{version_id}/publish",
        json={"expected_etag": draft_res.json()["version"]["etag"]},
        headers=sowner,
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["version"]["status"] == "PUBLISHED"
    assert pub_res.json()["version"]["manifest_hash"]

    # 8. Candidate generation job
    job_res = client.post(
        "/api/evaluations/candidate-jobs",
        json={
            "source_refs": [{"source_type": "FAQ", "source_id": "faq_wifi", "title": "公司 Wi-Fi 連線"}],
            "target_types": ["ANSWER_WITH_CITATION"],
            "requested_count": 2,
            "owner_unit_id": "IT Service Desk",
        },
        headers=kadmin,
    )
    assert job_res.status_code == 202
    job_id = job_res.json()["job_id"]
    assert job_res.json()["status"] == "COMPLETED"

    check_job = client.get(f"/api/evaluations/candidate-jobs/{job_id}", headers=kadmin)
    assert check_job.status_code == 200
    assert len(check_job.json()["created_candidate_case_ids"]) == 2

    # 9. Import dry-run & commit
    val_res = client.post(
        "/api/evaluations/imports/validate",
        json={
            "content": '{"title": "匯入題 1", "query": "印表機如何設定？", "behavior": "ANSWER_WITH_CITATION"}\n',
            "file_format": "JSONL",
            "owner_unit_id": "IT Service Desk",
        },
        headers=kadmin,
    )
    assert val_res.status_code == 200
    assert val_res.json()["is_valid"] is True
    staged_id = val_res.json()["staged_import_id"]

    commit_res = client.post(
        f"/api/evaluations/imports/{staged_id}/commit?owner_unit_id=IT%20Service%20Desk",
        headers=kadmin,
    )
    assert commit_res.status_code == 200
    assert commit_res.json()["total"] == 1

    # 10. Export cases
    export_res = client.post(
        "/api/evaluations/exports",
        json={"file_format": "CSV"},
        headers=sowner,
    )
    assert export_res.status_code == 200
    assert "VPN 設定指引" in export_res.json()["content"]


def test_quality_case_exposes_quality_case_sourced_evaluation_candidate(tmp_path: Path):
    app = create_app(_test_settings(tmp_path))
    client = TestClient(app)
    kadmin = auth_headers("KNOWLEDGE_ADMIN", "quality_author")
    actor = ActorContext(
        "quality_author",
        "Knowledge Admin",
        "KNOWLEDGE_ADMIN",
        ("IT Service Desk",),
        "local-development",
    )

    candidate = app.state.quality_service.add_candidate(
        source_type="MANUAL",
        case_type="KNOWLEDGE_GAP",
        title="VPN 驗收閉環測試",
        description="VPN 無法連線時的處理指引",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT Service Desk",
        actor=actor,
    )["candidate"]
    merge_res = client.post(
        "/api/quality-candidates/merge",
        headers=kadmin,
        json={
            "candidate_ids": [candidate["candidate_id"]],
            "title": "VPN 驗收閉環測試",
            "description": "VPN 無法連線時的處理指引",
            "priority": "MEDIUM",
            "assignee_id": "quality_author",
            "target_due_at": None,
        },
    )
    assert merge_res.status_code == 200, merge_res.text
    quality_case_id = merge_res.json()["case"]["case_id"]

    eval_res = client.post(
        "/api/evaluations/cases",
        headers=kadmin,
        json={
            "title": "VPN 改善驗收候選",
            "query": "VPN 無法連線時要如何處理？",
            "owner_unit_id": "IT Service Desk",
            "source_type": "QUALITY_CASE",
            "source_id": quality_case_id,
            "metadata": {"quality_case_id": quality_case_id},
        },
    )
    assert eval_res.status_code == 201, eval_res.text

    detail_res = client.get(f"/api/quality-cases/{quality_case_id}", headers=kadmin)
    assert detail_res.status_code == 200, detail_res.text
    linked = detail_res.json()["evaluation_candidates"]
    assert len(linked) == 1
    assert linked[0]["case"]["case_id"] == eval_res.json()["case"]["case_id"]
    assert linked[0]["current_revision"]["provenance"]["source_id"] == quality_case_id
