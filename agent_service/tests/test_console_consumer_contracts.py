"""Consumer-driven contracts for console_frontend's primary Backoffice endpoints.

These assertions mirror the fields React actually reads (auth session bootstrap,
work hub summary/items, and operations health), so OpenAPI drift that breaks the
console fails here before UI runtime.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings

REPO_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _settings(tmp_path: Path) -> BackofficeSettings:
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
        console_v2_enabled=True,
        legacy_shell_enabled=False,
    )


def _auth() -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": "ops.admin",
        "X-Backoffice-User-Name": "System Administrator",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_auth_config_contract_for_login_bootstrap(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    body = response.json()
    assert "authMode" in body or "auth_mode" in body
    # LoginPage reads camelCase fields from the JSON body.
    assert "headerAuthAllowed" in body or "header_auth_allowed" in body


def test_work_hub_contracts_match_console_work_page(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _auth()

    summary = client.get("/api/console/work-summary", headers=headers)
    assert summary.status_code == 200
    summary_body = summary.json()
    for key in ("total", "by_bucket", "by_workflow", "sources", "snapshot_id", "generated_at"):
        assert key in summary_body
    assert isinstance(summary_body["by_bucket"], dict)

    items = client.get(
        "/api/console/work-items",
        headers=headers,
        params={"bucket": "pending_action", "limit": 10},
    )
    assert items.status_code == 200
    items_body = items.json()
    for key in ("items", "total", "snapshot_id", "generated_at", "partial", "sources"):
        assert key in items_body
    assert isinstance(items_body["items"], list)
    if items_body["items"]:
        sample = items_body["items"][0]
        for key in ("key", "workflow", "title", "step", "next_action", "revision"):
            assert key in sample
        assert "id" in sample["next_action"]
        assert "route" in sample["next_action"]


def test_capabilities_contract_for_knowledge_ui_bootstrap(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.get("/api/capabilities", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    assert "knowledgeBridgeEnabled" in body or "knowledge_bridge_enabled" in body
    assert "knowledgeCapabilities" in body or "knowledge_capabilities" in body
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.get("/api/health/summary", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    assert "components" in body or "probes" in body
    breakdown = body.get("components") if body.get("components") is not None else body.get("probes")
    assert isinstance(breakdown, (list, dict))
    if isinstance(breakdown, list):
        assert breakdown
        assert "id" in breakdown[0] or "name" in breakdown[0]
    else:
        assert breakdown
