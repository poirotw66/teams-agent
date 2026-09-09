from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.governance_domain.models import FlagVersion, GovernanceState
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
        sync_store_path=tmp_path / "sync.json",
        quality_store_path=tmp_path / "quality.json",
    )


def _headers(role: str, user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_governance_search_status_filtering_and_attributes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    admin = _headers("SYSTEM_ADMIN")

    # 1. Unfiltered search: verify every hit has a 'status' attribute
    res_all = client.get("/api/governance/search", params={"q": "issue"}, headers=admin)
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert "hits" in data_all or "items" in data_all
    items = data_all.get("items", [])
    assert len(items) > 0
    for item in items:
        assert "status" in item, f"Missing status in search hit: {item}"

    # 2. Filtered search by status=ACTIVE
    res_active = client.get("/api/governance/search", params={"status": "ACTIVE"}, headers=admin)
    assert res_active.status_code == 200
    data_active = res_active.json()
    for item in data_active.get("items", []):
        assert item["status"].upper() == "ACTIVE"

    # 3. Filtered search by nonexistent status
    res_none = client.get("/api/governance/search", params={"status": "NONEXISTENT_STATUS"}, headers=admin)
    assert res_none.status_code == 200
    assert len(res_none.json().get("items", [])) == 0


def test_governance_search_external_source_warnings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    admin = _headers("SYSTEM_ADMIN")

    query_svc = app.state.query_service
    with patch.object(
        query_svc,
        "_fetch_document_inventory",
        side_effect=RuntimeError("Knowledge connection timeout"),
    ):
        res = client.get("/api/governance/search", params={"q": "test"}, headers=admin)
        assert res.status_code == 200
        data = res.json()
        assert "warnings" in data
        assert any("知識文件資料來源讀取失敗" in w for w in data["warnings"])
        assert any("Knowledge connection timeout" in w for w in data["warnings"])


def test_governance_retention_purge_and_core_preservation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    gov = app.state.governance_service
    admin_actor = ActorContext("admin", "Admin", "SYSTEM_ADMIN", ("IT Service Desk",))

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=400)

    # Add an expired candidate flag version (> 365 days) and an active flag version
    flags_before = gov.list_flags(actor=admin_actor)
    assert len(flags_before) > 0
    target_flag = flags_before[0]
    target_flag_id = target_flag["flag"]["flag_id"]
    active_ver_id = target_flag["flag"]["active_version_id"]

    old_candidate = FlagVersion(
        version_id="old-cand-1234",
        flag_id=target_flag_id,
        status="CANDIDATE",
        value="ENABLED",
        environment="lab",
        audience="all",
        effective_at=old_time,
        expires_at=None,
        created_by="tester",
        created_at=old_time,
    )

    def add_old_candidate(curr: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
        return curr.model_copy(
            update={
                "revision": curr.revision + 1,
                "flag_versions": (*curr.flag_versions, old_candidate),
            }
        ), {}

    gov._repository.mutate(add_old_candidate)

    # Verify old candidate is in versions
    flags_with_old = gov.list_flags(actor=admin_actor)
    target_with_old = next(f for f in flags_with_old if f["flag"]["flag_id"] == target_flag_id)
    version_ids_before = [v["version_id"] for v in target_with_old["versions"]]
    assert "old-cand-1234" in version_ids_before
    if active_ver_id:
        assert active_ver_id in version_ids_before

    # Run purge_expired with 365 days retention
    purge_res = gov.purge_expired(actor=admin_actor, retention_days=365, now=now)
    assert purge_res["flagVersions"] >= 1
    assert (
        "Core active, approved, canary, and previous-healthy versions retained permanently"
        in purge_res["retentionPolicy"]
    )

    # Verify old candidate is purged while active version is retained permanently
    flags_after = gov.list_flags(actor=admin_actor)
    target_after = next(f for f in flags_after if f["flag"]["flag_id"] == target_flag_id)
    version_ids_after = [v["version_id"] for v in target_after["versions"]]
    assert "old-cand-1234" not in version_ids_after
    if active_ver_id:
        assert active_ver_id in version_ids_after


def test_admin_retention_purge_endpoint_includes_governance(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    admin = _headers("SYSTEM_ADMIN")

    res = client.post("/api/admin/retention/purge", headers=admin)
    assert res.status_code == 200
    data = res.json()
    assert "governance" in data
    assert "totalRemoved" in data
    assert "retentionPolicy" in data["governance"]
