"""Automated test suite for AI Ops Backoffice Console V2 aggregation and workflow routes."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.quality_domain import FileQualityRepository, QualityService
from ai_ops_backoffice.settings import BackofficeSettings

REPO_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _build_settings(
    tmp_path: Path,
    *,
    console_v2_enabled: bool = True,
    legacy_shell_enabled: bool = False,
) -> BackofficeSettings:
    return BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=REPO_DATA_DIR / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=REPO_DATA_DIR / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=REPO_DATA_DIR / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
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
        legacy_shell_enabled=legacy_shell_enabled,
    )


def _auth_headers(role: str = "KNOWLEDGE_ADMIN", user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def _seed_sample_quality_case(
    quality_service: QualityService,
    *,
    actor: ActorContext,
    title: str = "VPN 連線中斷頻繁",
) -> str:
    seed_event = f"event-seed-{uuid.uuid4().hex[:8]}"
    cand1 = quality_service.add_candidate(
        source_type="EVENT",
        case_type="NO_ANSWER",
        title=title,
        description="使用者遭遇連線問題",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT Service Desk",
        source_event_ids=(seed_event,),
        conversation_refs=(f"conv-{seed_event}",),
        frequency=5,
        negative_rate=0.4,
        handoff_rate=0.2,
        estimated_cost_impact=50,
        actor=actor,
    )["candidate"]

    case = quality_service.merge_candidates(
        candidate_ids=(cand1["candidate_id"],),
        title=title,
        description="改善 VPN 連線 FAQ 與說明文件",
        priority="HIGH",
        assignee_id=actor.user_id,
        target_due_at=None,
        actor=actor,
    )["case"]

    return str(case["case_id"])


def _advance_case(
    quality_service: QualityService,
    case_id: str,
    status: str,
    *,
    actor: ActorContext,
    reason: str | None = None,
    resolution_type: str | None = None,
) -> dict[str, Any]:
    detail = quality_service.case_detail(case_id, actor=actor)
    current_etag = detail["case"]["etag"]
    return quality_service.transition_case(
        case_id,
        status=status,
        reason=reason,
        resolution_type=resolution_type,
        expected_etag=current_etag,
        actor=actor,
    )["case"]


def test_work_items_empty_and_summary_empty(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    items_res = client.get("/api/console/work-items", headers=_auth_headers())
    assert items_res.status_code == 200
    data = items_res.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["next_cursor"] is None
    assert data["sources"]["quality_case"] == "ok"

    summary_res = client.get("/api/console/work-summary", headers=_auth_headers())
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["total"] == 0
    assert summary["by_bucket"] == {
        "pending_action": 0,
        "pending_review": 0,
        "tracking": 0,
        "completed": 0,
    }


def test_work_items_bucket_filtering_and_pagination(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    admin_actor = ActorContext("user-admin", "Admin", "KNOWLEDGE_ADMIN", ("IT Service Desk",))
    quality_repo = FileQualityRepository(tmp_path / "quality.json")
    quality_service = QualityService(quality_repo)

    case_id_1 = _seed_sample_quality_case(quality_service, actor=admin_actor, title="案件 1: 待分流")
    case_id_2 = _seed_sample_quality_case(quality_service, actor=admin_actor, title="案件 2: 修正中")
    _advance_case(quality_service, case_id_2, "TRIAGED", actor=admin_actor)
    _advance_case(quality_service, case_id_2, "IN_PROGRESS", actor=admin_actor)

    case_id_3 = _seed_sample_quality_case(quality_service, actor=admin_actor, title="案件 3: 審核中")
    _advance_case(quality_service, case_id_3, "TRIAGED", actor=admin_actor)
    _advance_case(quality_service, case_id_3, "IN_PROGRESS", actor=admin_actor)
    _advance_case(quality_service, case_id_3, "WAITING_REVIEW", actor=admin_actor)

    owner_actor = ActorContext("user-owner", "Owner", "SERVICE_OWNER", ("IT Service Desk",))
    case_id_4 = _seed_sample_quality_case(quality_service, actor=admin_actor, title="案件 4: 已結案")
    _advance_case(quality_service, case_id_4, "WONT_FIX", reason="不需調整", actor=owner_actor)

    headers = _auth_headers(user_id="user-admin")

    invalid_bucket_res = client.get("/api/console/work-items?bucket=invalid_bucket", headers=headers)
    assert invalid_bucket_res.status_code == 400

    all_res = client.get("/api/console/work-items?bucket=all", headers=headers)
    assert all_res.status_code == 200
    assert all_res.json()["total"] == 4

    action_res = client.get("/api/console/work-items?bucket=pending_action", headers=headers)
    assert action_res.status_code == 200
    action_items = action_res.json()["items"]
    assert len(action_items) == 2
    action_source_ids = {item["source_id"] for item in action_items}
    assert case_id_1 in action_source_ids
    assert case_id_2 in action_source_ids

    review_res = client.get("/api/console/work-items?bucket=pending_review", headers=headers)
    assert review_res.status_code == 200
    review_items = review_res.json()["items"]
    assert len(review_items) == 1
    assert review_items[0]["source_id"] == case_id_3

    completed_res = client.get("/api/console/work-items?bucket=completed", headers=headers)
    assert completed_res.status_code == 200
    completed_items = completed_res.json()["items"]
    assert len(completed_items) == 1
    assert completed_items[0]["source_id"] == case_id_4

    page1_res = client.get("/api/console/work-items?bucket=all&limit=2", headers=headers)
    assert page1_res.status_code == 200
    page1 = page1_res.json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    cursor = page1["next_cursor"]
    page2_res = client.get(f"/api/console/work-items?bucket=all&limit=2&cursor={cursor}", headers=headers)
    assert page2_res.status_code == 200
    page2 = page2_res.json()
    assert len(page2["items"]) == 2
    assert page2["next_cursor"] is None

    p1_keys = {item["key"] for item in page1["items"]}
    p2_keys = {item["key"] for item in page2["items"]}
    assert p1_keys.isdisjoint(p2_keys)

    other_user_headers = _auth_headers(user_id="user-different")
    replay_res = client.get(
        f"/api/console/work-items?bucket=all&limit=2&cursor={cursor}",
        headers=other_user_headers,
    )
    assert replay_res.status_code == 200
    replay_items = replay_res.json()["items"]
    assert {item["key"] for item in replay_items} == p1_keys


def test_work_summary_aggregation(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    admin_actor = ActorContext("user-admin", "Admin", "KNOWLEDGE_ADMIN", ("IT Service Desk",))
    quality_repo = FileQualityRepository(tmp_path / "quality.json")
    quality_service = QualityService(quality_repo)

    _seed_sample_quality_case(quality_service, actor=admin_actor, title="案件 A")
    c2 = _seed_sample_quality_case(quality_service, actor=admin_actor, title="案件 B")
    _advance_case(quality_service, c2, "TRIAGED", actor=admin_actor)
    _advance_case(quality_service, c2, "IN_PROGRESS", actor=admin_actor)
    _advance_case(quality_service, c2, "WAITING_REVIEW", actor=admin_actor)

    summary_res = client.get("/api/console/work-summary", headers=_auth_headers())
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["total"] == 2
    assert summary["by_bucket"]["pending_action"] == 1
    assert summary["by_bucket"]["pending_review"] == 1
    assert summary["by_workflow"]["quality_improvement"] == 2


def test_workflow_detail_stages_and_evidence(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    admin_actor = ActorContext("user-admin", "Admin", "KNOWLEDGE_ADMIN", ("IT Service Desk",))
    quality_repo = FileQualityRepository(tmp_path / "quality.json")
    quality_service = QualityService(quality_repo)

    case_id = _seed_sample_quality_case(quality_service, actor=admin_actor, title="審核流程測試")

    detail_res = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=_auth_headers())
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["kind"] == "quality_case"
    assert detail["id"] == case_id
    assert detail["status"] == "NEW"
    assert len(detail["stages"]) == 5

    stage_ids = [s["id"] for s in detail["stages"]]
    assert stage_ids == ["triage", "fix_content", "verification_review", "observation", "resolution"]
    assert detail["stages"][0]["status"] == "current"
    assert detail["stages"][1]["status"] == "pending"

    assert "triage" in detail["allowed_actions"]
    assert len(detail["evidence_refs"]) >= 1
    assert detail["evidence_refs"][0]["source_type"] == "quality_candidate"
    assert detail["evidence_refs"][0]["relation"] == "source_issue"

    _advance_case(quality_service, case_id, "TRIAGED", actor=admin_actor)
    _advance_case(quality_service, case_id, "IN_PROGRESS", actor=admin_actor)
    _advance_case(quality_service, case_id, "WAITING_REVIEW", actor=admin_actor)

    detail_res2 = client.get(f"/api/console/workflows/quality_case/{case_id}", headers=_auth_headers())
    assert detail_res2.status_code == 200
    detail2 = detail_res2.json()
    assert detail2["status"] == "WAITING_REVIEW"
    assert detail2["stages"][0]["status"] == "completed"
    assert detail2["stages"][1]["status"] == "completed"
    assert detail2["stages"][2]["status"] == "current"
    assert "start_observation" in detail2["allowed_actions"]

    not_found_kind = client.get(f"/api/console/workflows/unknown_kind/{case_id}", headers=_auth_headers())
    assert not_found_kind.status_code == 404

    not_found_case = client.get("/api/console/workflows/quality_case/nonexistent-case", headers=_auth_headers())
    assert not_found_case.status_code == 404


def test_console_v2_feature_flag_redirect(tmp_path: Path) -> None:
    settings_disabled = _build_settings(tmp_path, console_v2_enabled=False)
    app_disabled = create_app(settings_disabled)
    client_disabled = TestClient(app_disabled)

    res = client_disabled.get("/console-v2/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/"

    deep_res = client_disabled.get("/console-v2/work", follow_redirects=False)
    assert deep_res.status_code == 307
    assert deep_res.headers["location"] == "/"

    settings_enabled = _build_settings(tmp_path, console_v2_enabled=True)
    app_enabled = create_app(settings_enabled)
    client_enabled = TestClient(app_enabled)

    root_res = client_enabled.get("/", follow_redirects=False)
    assert root_res.status_code == 307
    assert root_res.headers["location"] == "/console-v2/dashboard"

    legacy_disabled = client_enabled.get("/legacy", follow_redirects=False)
    assert legacy_disabled.status_code == 307
    assert legacy_disabled.headers["location"] == "/console-v2/dashboard"

    stub_res = client_enabled.get("/static/js/main.js")
    assert stub_res.status_code == 200
    stub_body = stub_res.text
    assert "/console-v2/dashboard" in stub_body
    assert "from \"./api.js\"" not in stub_body
