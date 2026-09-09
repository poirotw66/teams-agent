from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from governance_eval_helpers import release_eligible_lab_harness

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.governance_domain import FileGovernanceRepository
from ai_ops_backoffice.governance_domain.models import GovernanceAuditEvent
from ai_ops_backoffice.governance_domain.service import GovernanceService
from ai_ops_backoffice.settings import BackofficeSettings


def _make_settings(tmp_path: Path) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    return BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=store_path,
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="FILE",
        pricing_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT",
        entra_tenant_id=None,
        entra_client_id=None,
    )


def _headers(role: str = "SYSTEM_ADMIN", user_id: str = "test.auditor") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id,
        "X-Backoffice-User-Name": "Auditor User",
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT",
    }


def test_governance_search_audit_mixin_filtering_and_pagination(tmp_path: Path) -> None:
    gov_file = tmp_path / "governance.json"
    gov_service = GovernanceService(
        FileGovernanceRepository(gov_file),
        eval_flow_harness=release_eligible_lab_harness(),
    )
    actor_admin = ActorContext(
        user_id="alice.admin",
        display_name="Alice Admin",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )

    base_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    # Seed diverse governance audit events
    events = [
        GovernanceAuditEvent(
            audit_id=f"audit-{i}",
            action="PROMPT_ACTIVATED" if i % 2 == 0 else "MODEL_CONFIG_SAVED",
            actor_id="alice.admin" if i < 3 else "bob.reviewer",
            actor_role="SYSTEM_ADMIN",
            target_type="PROMPT" if i % 2 == 0 else "MODEL",
            target_id=f"target-{i}",
            result="SUCCESS",
            reason=f"Update reason {i}",
            occurred_at=base_time + timedelta(hours=i),
        )
        for i in range(6)
    ]
    gov_service._repository.mutate(
        lambda curr: (curr.model_copy(update={"revision": curr.revision + 1, "audits": tuple(events)}), {})
    )

    # 1. Filter by actor_id
    alice_audits = gov_service.query_audit(actor=actor_admin, actor_id="alice.admin")
    assert alice_audits["total"] == 3
    assert len(alice_audits["items"]) == 3
    assert all(item["actor_id"] == "alice.admin" for item in alice_audits["items"])

    # 2. Filter by action
    prompt_actions = gov_service.query_audit(actor=actor_admin, action="PROMPT_ACTIVATED")
    assert prompt_actions["total"] == 3
    assert all(item["action"] == "PROMPT_ACTIVATED" for item in prompt_actions["items"])

    # 3. Filter by target_type
    model_audits = gov_service.query_audit(actor=actor_admin, target_type="MODEL")
    assert model_audits["total"] == 3
    assert all(item["target_type"] == "MODEL" for item in model_audits["items"])

    # 4. Filter by date range
    mid_audits = gov_service.query_audit(
        actor=actor_admin,
        start_date="2026-09-01T12:00:00Z",
        end_date="2026-09-01T14:00:00Z",
    )
    assert mid_audits["total"] == 3

    # 5. Pagination (limit=2)
    page1 = gov_service.query_audit(actor=actor_admin, limit=2)
    assert len(page1["items"]) == 2
    assert page1["hasMore"] is True
    assert page1["nextCursor"] == "2"

    page2 = gov_service.query_audit(actor=actor_admin, limit=2, cursor=page1["nextCursor"])
    assert len(page2["items"]) == 2
    assert page2["hasMore"] is True
    assert page2["nextCursor"] == "4"

    # 6. Backward compatible list_audit
    legacy_list = gov_service.list_audit(actor=actor_admin, target_type="PROMPT")
    assert isinstance(legacy_list, list)
    assert len(legacy_list) == 3


def test_governance_audit_api_endpoints_and_rbac(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    # 1. Without ops.audit.read (e.g. SERVICE_OWNER lacks ops.audit.read) -> 403 Forbidden
    res_forbidden = client.get("/api/governance/audit", headers=_headers("SERVICE_OWNER"))
    assert res_forbidden.status_code == 403
    assert "Forbidden" in res_forbidden.text or "capability" in res_forbidden.text

    # 2. With AUDITOR or SYSTEM_ADMIN (has ops.audit.read) -> 200 OK
    res_ok = client.get("/api/governance/audit", headers=_headers("AUDITOR"))
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert "items" in data
    assert "nextCursor" in data
    assert "hasMore" in data
    assert "total" in data

    # 3. Query with nonexistent actor_id -> 200 OK with empty list (查無資料，非讀取失敗)
    res_empty = client.get("/api/governance/audit?actor_id=nonexistent.user.999", headers=_headers("SYSTEM_ADMIN"))
    assert res_empty.status_code == 200
    empty_data = res_empty.json()
    assert empty_data["items"] == []
    assert empty_data["total"] == 0
    assert empty_data["hasMore"] is False

    # 4. Export endpoint with actor_id filter -> 200 OK
    res_export = client.get(
        "/api/governance/audit/export?target_type=PROMPT",
        headers=_headers("AUDITOR"),
    )
    assert res_export.status_code == 200
    export_data = res_export.json()
    assert "exportedAt" in export_data
    assert "items" in export_data
    assert export_data["targetType"] == "PROMPT"


def test_cross_domain_operator_traceability(tmp_path: Path) -> None:
    """Verify that all critical operations of a specific operator can be queried across both ops and governance."""
    settings = _make_settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    operator_id = "security.lead.789"
    headers_operator = _headers("AI_ADMIN", user_id=operator_id)

    # Operator performs a pricing rate change (Ops domain)
    res_rate = client.post(
        "/api/costs/rates",
        headers=headers_operator,
        json={
            "model": "gemini-2.0-flash",
            "inputPerMillion": 0.15,
            "outputPerMillion": 0.60,
            "reason": "Quarterly rate review by security lead",
        },
    )
    assert res_rate.status_code == 200

    # Query operational audit for this operator
    res_ops_audit = client.get(
        f"/api/audit-events?actor_id={operator_id}",
        headers=_headers("AUDITOR"),
    )
    assert res_ops_audit.status_code == 200
    ops_items = res_ops_audit.json()["items"]
    assert len(ops_items) >= 1
    assert any(item["actor_id"] == operator_id for item in ops_items)

    # Query governance audit for this operator
    res_gov_audit = client.get(
        f"/api/governance/audit?actor_id={operator_id}",
        headers=_headers("AUDITOR"),
    )
    assert res_gov_audit.status_code == 200
    gov_data = res_gov_audit.json()
    assert "items" in gov_data
    assert "total" in gov_data
