from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings


def _settings(tmp_path: Path) -> BackofficeSettings:
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
    )


def headers(role: str, user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def _verify_examples(client: TestClient, system: dict[str, str]) -> dict:
    payloads = [
        {
            "text": "VPN 無法連線",
            "expected_issue_type_id": "vpn.connection_failed",
            "expected_route": "KNOWLEDGE",
            "label": "POSITIVE",
        },
        {
            "text": "Outlook 寄信失敗",
            "expected_issue_type_id": "email.outlook_sync",
            "expected_route": "KNOWLEDGE",
            "label": "POSITIVE",
        },
        {
            "text": "請幫我轉接真人客服",
            "expected_issue_type_id": "other.unclassified",
            "expected_route": "HANDOFF",
            "label": "POSITIVE",
        },
    ]
    verified = None
    for payload in payloads:
        created = client.post("/api/examples/manual", headers=system, json=payload).json()["example"]
        verified = client.post(
            f"/api/examples/{created['example_id']}/review",
            headers=system,
            json={"expected_etag": 1, "approve": True, "reason": "verified for phase3"},
        ).json()["example"]
    assert verified is not None
    return verified


def test_governance_prompt_api_lifecycle(tmp_path: Path) -> None:
    from governance_eval_helpers import release_eligible_lab_harness

    client = TestClient(
        create_app(_settings(tmp_path), eval_flow_harness=release_eligible_lab_harness())
    )
    system = headers("SYSTEM_ADMIN", "sys-writer")
    verified = _verify_examples(client, system)
    ai = headers("AI_ADMIN", "ai-writer")
    approver = headers("AI_ADMIN", "ai-approver")
    prompts = client.get("/api/governance/prompts", headers=ai)
    assert prompts.status_code == 200
    prompt_id = prompts.json()["items"][0]["prompt"]["prompt_id"]
    taxonomy_version = client.get("/api/taxonomy", headers=ai).json()["taxonomyVersion"]
    candidate = client.post(
        f"/api/governance/prompts/{prompt_id}/candidates",
        headers={**ai, "Idempotency-Key": "gov-1"},
        json={
            "dataset_version": verified["dataset_version"],
            "taxonomy_version": taxonomy_version,
            "knowledge_release_id": "release-test",
        },
    )
    assert candidate.status_code == 200
    version_id = candidate.json()["version"]["version_id"]
    assert client.post(
        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/approve",
        headers=approver,
        json={"reason": "skip eval", "approved": True},
    ).status_code == 422
    evaluated = client.post(
        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/eval",
        headers=ai,
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["eval"]["critical_passed"] is True
    assert evaluated.json()["eval"]["status"] == "COMPLETED"
    approved = client.post(
        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/approve",
        headers=approver,
        json={"reason": "dual control approve"},
    )
    assert approved.status_code == 200
    canary = client.post(
        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/canary",
        headers=approver,
        json={"percent": 5, "environment": "prod", "reason": "start canary"},
    )
    assert canary.status_code == 200
    activated = client.post(
        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/activate",
        headers=approver,
        json={"reason": "promote"},
    )
    assert activated.status_code == 200
    assert activated.json()["version"]["status"] == "ACTIVE"
    flags = client.get("/api/governance/flags", headers=ai)
    assert flags.status_code == 200
    assert any(item["flag"]["flag_id"] == "ticket_mode" for item in flags.json()["items"])
    search = client.get("/api/governance/search", params={"q": "issue-extractor"}, headers=ai)
    assert search.status_code == 200
    assert search.json()["count"] >= 1
    assert client.get("/api/governance/search", params={"q": "issue-extractor"}, headers=headers("ANALYST")).status_code == 403


def test_governance_canary_evaluate_stops_and_audit_export(tmp_path: Path) -> None:
    from governance_eval_helpers import release_eligible_lab_harness

    client = TestClient(
        create_app(_settings(tmp_path), eval_flow_harness=release_eligible_lab_harness())
    )
    system = headers("SYSTEM_ADMIN", "sys-writer")
    verified = _verify_examples(client, system)
    ai = headers("AI_ADMIN", "ai-writer")
    approver = headers("AI_ADMIN", "ai-approver")
    prompts = client.get("/api/governance/prompts", headers=ai).json()
    prompt_id = prompts["items"][0]["prompt"]["prompt_id"]
    taxonomy_version = client.get("/api/taxonomy", headers=ai).json()["taxonomyVersion"]
    version_id = client.post(
        f"/api/governance/prompts/{prompt_id}/candidates",
        headers={**ai, "Idempotency-Key": "gov-canary-1"},
        json={
            "dataset_version": verified["dataset_version"],
            "taxonomy_version": taxonomy_version,
        },
    ).json()["version"]["version_id"]
    assert client.post(
        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/eval",
        headers=ai,
    ).status_code == 200
    assert client.post(
        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/approve",
        headers=approver,
        json={"reason": "approve canary candidate"},
    ).status_code == 200
    assert client.post(
        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/canary",
        headers=approver,
        json={"percent": 10, "environment": "lab", "reason": "start canary"},
    ).status_code == 200
    stopped = client.post(
        f"/api/governance/prompts/{prompt_id}/canary/evaluate",
        headers=approver,
        json={
            "sample_size": 50,
            "error_rate": 0.2,
            "negative_feedback_rate": 0.1,
            "handoff_rate": 0.1,
            "safety_alerts": 0,
        },
    )
    assert stopped.status_code == 200
    assert stopped.json()["action"] == "STOP"
    detail = client.get(f"/api/governance/prompts/{prompt_id}", headers=ai).json()
    assert detail["prompt"]["canary_version_id"] is None
    exported = client.get("/api/governance/audit/export", headers=system)
    assert exported.status_code == 200
    body = exported.json()
    assert body["format"] == "json"
    assert body["count"] >= 1
    assert any(item["action"] == "PROMPT_CANARY_STOPPED" for item in body["items"])


def test_retention_masking_roles_api(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    ai = headers("AI_ADMIN", "ai-writer")
    approver = headers("AI_ADMIN", "ai-approver")
    system = headers("SYSTEM_ADMIN", "sys-writer")
    system_b = headers("SYSTEM_ADMIN", "sys-approver")

    retention = client.get("/api/governance/retention", headers=ai)
    assert retention.status_code == 200
    assert any(item["status"] == "ACTIVE" for item in retention.json()["items"])

    masking = client.get("/api/governance/masking", headers=ai)
    assert masking.status_code == 200
    assert any(item["status"] == "ACTIVE" for item in masking.json()["items"])

    created_mask = client.post(
        "/api/governance/masking/candidates",
        headers=ai,
        json={"policy_version": "v3", "reason": "api masking"},
    )
    assert created_mask.status_code == 200
    mask_id = created_mask.json()["policy"]["version_id"]
    assert client.post(
        f"/api/governance/masking/{mask_id}/approve",
        headers=approver,
        json={"reason": "approve masking"},
    ).status_code == 200
    assert client.post(
        f"/api/governance/masking/{mask_id}/activate",
        headers=approver,
        json={"reason": "activate masking"},
    ).status_code == 200

    role = client.post(
        "/api/governance/roles/requests",
        headers=system,
        json={
            "target_principal": "analyst.api",
            "target_role": "ANALYST",
            "add_capabilities": ["ops.summary.read"],
            "remove_capabilities": [],
            "reason": "grant analyst summary",
        },
    )
    assert role.status_code == 200
    change_id = role.json()["change"]["change_id"]
    assert client.post(
        f"/api/governance/roles/{change_id}/approve",
        headers=system_b,
        json={"reason": "approve role"},
    ).status_code == 200
    roles = client.get("/api/governance/roles", headers=system)
    assert roles.status_code == 200
    assert any(item["change_id"] == change_id for item in roles.json()["items"])


def test_operations_summary_respects_cost_display_flag(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    ai = headers("AI_ADMIN", "ai-cost")
    summary = client.get("/api/operations/summary?days=7", headers=ai)
    assert summary.status_code == 200
    assert summary.json().get("costDisplayEnabled") is True
    created = client.post(
        "/api/governance/flags/candidates",
        headers=ai,
        json={
            "flag_id": "cost_display",
            "value": "false",
            "environment": "lab",
            "reason": "hide cost in lab",
        },
    )
    assert created.status_code == 200
    version_id = created.json()["version"]["version_id"]
    approver = headers("AI_ADMIN", "ai-cost-approver")
    assert client.post(
        f"/api/governance/flags/cost_display/versions/{version_id}/approve",
        headers=approver,
        json={"reason": "approve hide"},
    ).status_code == 200
    assert client.post(
        f"/api/governance/flags/cost_display/versions/{version_id}/activate",
        headers=approver,
        json={"reason": "activate hide"},
    ).status_code == 200
    hidden = client.get("/api/operations/summary?days=7", headers=ai)
    assert hidden.status_code == 200
    payload = hidden.json()
    assert payload["costDisplayEnabled"] is False
    assert payload["estimatedCostUsd"] is None
    assert payload["costCoverage"] is None


def test_eval_harness_status_endpoint(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.get("/api/governance/eval-harness", headers=headers("AI_ADMIN"))
    assert response.status_code == 200
    body = response.json()
    assert "available" in body
    assert "releaseEligible" in body
    assert "mode" in body
    assert body["configured"] is True
