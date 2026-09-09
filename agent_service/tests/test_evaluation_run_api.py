from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings


def _test_settings(tmp_path: Path) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    rel_dir = releases_dir / "release-001" / "index"
    rel_dir.mkdir(parents=True, exist_ok=True)
    (rel_dir / "chunks.json").write_text(
        json.dumps({
            "version": 1,
            "chunks": [
                {
                    "chunk_id": "c1",
                    "title": "IT密碼政策",
                    "source_id": "doc_pwd_policy",
                    "source_path": "sources/pwd.md",
                    "content": "密碼每三個月定期更換一次。",
                }
            ],
        }),
        encoding="utf-8",
    )

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
        eval_store_mode="MEMORY",
        eval_store_path=tmp_path / "golden_evals.json",
    )


def auth_headers(role: str, user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk,HR",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_evaluation_run_api_lifecycle(tmp_path: Path):
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    kadmin_headers = auth_headers("KNOWLEDGE_ADMIN", "u_kadmin")
    sowner_headers = auth_headers("SERVICE_OWNER", "u_sowner")
    aiadmin_headers = auth_headers("AI_ADMIN", "u_aiadmin")

    # 1. Create case, submit, approve
    case_res = client.post(
        "/api/evaluations/cases",
        headers=kadmin_headers,
        json={
            "title": "密碼更換規定",
            "query": "密碼多久要更換？",
            "owner_unit_id": "IT Service Desk",
            "behavior": "ANSWER_WITH_CITATION",
            "required_facts": [{"criterion_id": "f1", "description": "每三個月定期更換"}],
            "evidence": [
                {
                    "group_id": "g1",
                    "items": [{"evidence_id": "e1", "source_type": "DOCUMENT", "source_id": "doc_pwd_policy"}],
                }
            ],
            "source_type": "DOCUMENT",
            "source_id": "doc_pwd_policy",
        },
    )
    case_id = case_res.json()["case"]["case_id"]
    rev_id = case_res.json()["revision"]["revision_id"]

    sub_res = client.post(
        f"/api/evaluations/cases/{case_id}/revisions/{rev_id}/submit",
        headers=kadmin_headers,
        json={"expected_etag": 1},
    )
    assert sub_res.status_code == 200

    appr_res = client.post(
        f"/api/evaluations/cases/{case_id}/revisions/{rev_id}/review",
        headers=sowner_headers,
        json={"approve": True, "reason": "Approved", "expected_etag": 2},
    )
    assert appr_res.status_code == 200

    # 2. Create set, draft version, publish
    set_res = client.post(
        "/api/evaluations/sets",
        headers=kadmin_headers,
        json={"name": "IT 驗收題庫", "owner_unit_ids": ["IT Service Desk"], "purpose": "DEVELOPMENT"},
    )
    set_id = set_res.json()["eval_set"]["set_id"]

    ver_res = client.post(
        f"/api/evaluations/sets/{set_id}/versions",
        headers=kadmin_headers,
        json={"case_revision_ids": [rev_id]},
    )
    set_version_id = ver_res.json()["version"]["set_version_id"]

    pub_res = client.post(
        f"/api/evaluations/sets/{set_id}/versions/{set_version_id}/publish",
        headers=sowner_headers,
        json={"expected_etag": 1},
    )
    assert pub_res.status_code == 200

    # 3. Preflight Run Check
    preflight_res = client.post(
        "/api/evaluations/runs/preflight",
        headers=aiadmin_headers,
        json={
            "set_version_id": set_version_id,
            "baseline_target": {"prompt_version": "default", "model_id": "gemini-2.5-flash"},
            "candidate_target": {"prompt_version": "candidate-v1", "model_id": "gemini-2.5-flash"},
        },
    )
    assert preflight_res.status_code == 200
    assert preflight_res.json()["is_valid"] is True
    assert preflight_res.json()["case_count"] == 1

    # 4. Create Run
    run_res = client.post(
        "/api/evaluations/runs",
        headers=aiadmin_headers,
        json={
            "set_version_id": set_version_id,
            "baseline_target": {"prompt_version": "default", "model_id": "gemini-2.5-flash"},
            "candidate_target": {"prompt_version": "candidate-v1", "model_id": "gemini-2.5-flash"},
            "mode": "REAL_RAG",
        },
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["run"]["run_id"]
    assert run_res.json()["run"]["status"] in {"RUNNING", "COMPLETED"}

    # 5. List Runs
    list_runs_res = client.get("/api/evaluations/runs", headers=aiadmin_headers)
    assert list_runs_res.status_code == 200
    assert any(r["run_id"] == run_id for r in list_runs_res.json())

    # 6. Get Run Detail
    get_run_res = client.get(f"/api/evaluations/runs/{run_id}", headers=aiadmin_headers)
    assert get_run_res.status_code == 200
    assert get_run_res.json()["run"]["run_id"] == run_id

    # 7. List Case Executions
    cases_res = client.get(f"/api/evaluations/runs/{run_id}/cases", headers=aiadmin_headers)
    assert cases_res.status_code == 200
    executions = cases_res.json()
    assert len(executions) >= 2  # baseline and candidate

    exec_id = executions[0]["execution_id"]
    get_exec_res = client.get(f"/api/evaluations/runs/{run_id}/cases/{exec_id}", headers=aiadmin_headers)
    assert get_exec_res.status_code == 200
    assert get_exec_res.json()["execution"]["execution_id"] == exec_id

    # 8. Human Review Decision (Service Owner)
    review_res = client.post(
        f"/api/evaluations/runs/{run_id}/reviews",
        headers=sowner_headers,
        json={
            "execution_id": exec_id,
            "metric_id": "retrieval.recall",
            "decision": "PASS",
            "reason": "Human Auditor verified that alternative retrieval source is valid",
        },
    )
    assert review_res.status_code == 200
    assert review_res.json()["review_decision"]["new_decision"] == "PASS"

    # 9. Rescore Run
    rescore_res = client.post(
        f"/api/evaluations/runs/{run_id}/rescore",
        headers=sowner_headers,
        json={
            "judge_version": "ge2-judge-v2",
            "metric_version": "ge2-metrics-v2",
        },
    )
    assert rescore_res.status_code == 200
    assert rescore_res.json()["run"]["judge_version"] == "ge2-judge-v2"


def test_evaluation_preflight_and_ui_assets(tmp_path: Path):
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    # Verify index.html contains updated asset version
    index_res = client.get("/")
    assert index_res.status_code == 200
    assert "ops-ui-20260909a" in index_res.text

    aiadmin_headers = auth_headers("AI_ADMIN", "u_aiadmin")
    # Verify preflight with non-existent set version returns 200 with is_valid=False and blocking_errors
    preflight_res = client.post(
        "/api/evaluations/runs/preflight",
        headers=aiadmin_headers,
        json={
            "set_version_id": "nonexistent_ver",
            "baseline_target": {"prompt_version": "v1", "model_id": "m1"},
            "candidate_target": {"prompt_version": "v2", "model_id": "m1"},
            "limits": {"max_cases": 10},
        },
    )
    assert preflight_res.status_code == 200
    assert preflight_res.json()["is_valid"] is False
    assert any("not found" in err for err in preflight_res.json()["blocking_errors"])

    # Verify preflight rejects invalid payload schema with 422
    schema_err_res = client.post(
        "/api/evaluations/runs/preflight",
        headers=aiadmin_headers,
        json={
            # Missing set_version_id and targets
            "limits": {"max_cases": 10},
        },
    )
    assert schema_err_res.status_code == 422
