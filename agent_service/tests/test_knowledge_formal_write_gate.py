"""Fail-closed cloud formal write gate and workspace labeling."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.knowledge_bridge.capabilities import knowledge_capabilities_for
from ai_ops_backoffice.knowledge_bridge.errors import KnowledgeBridgeError
from ai_ops_backoffice.knowledge_bridge.formal_write_gate import (
    FORMAL_CLOUD_WRITE_CAPABILITIES,
    assert_formal_cloud_write_allowed,
    evaluate_knowledge_workspace_gate,
    filter_knowledge_capabilities_for_workspace,
    resolve_console_surface,
    resolve_knowledge_workspace_mode,
)
from ai_ops_backoffice.settings import BackofficeSettings
from operations_core.access import ActorContext

SECRET = "test-formal-write-gate-secret"


def _settings(tmp_path: Path, **overrides: object) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    base = BackofficeSettings(
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
        knowledge_portal_url="http://knowledge-portal.test",
        knowledge_internal_url="http://knowledge-portal.test",
        knowledge_service_token="",
        knowledge_delegation_secret=SECRET,
        knowledge_bridge_enabled=True,
        knowledge_in_process=True,
        deployment_tenant_id="local-development",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        governance_store_path=tmp_path / "governance.json",
        relaxed_workflow=True,
    )
    return replace(base, **overrides) if overrides else base


def test_default_in_process_workspace_is_local_sandbox(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert resolve_knowledge_workspace_mode(settings) == "LOCAL_SANDBOX"
    gate = evaluate_knowledge_workspace_gate(settings)
    assert gate.workspace_mode == "LOCAL_SANDBOX"
    assert gate.cloud_formal_writes_allowed is False


def test_console_surface_follows_in_process_unless_explicit(tmp_path: Path) -> None:
    local = _settings(tmp_path, knowledge_in_process=True)
    assert resolve_console_surface(local) == "LOCAL"
    remote = _settings(tmp_path, knowledge_in_process=False)
    assert resolve_console_surface(remote) == "CLOUD"
    explicit_cloud = _settings(
        tmp_path,
        knowledge_in_process=True,
        console_surface="CLOUD",
        knowledge_workspace_mode="LOCAL_SANDBOX",
    )
    assert resolve_console_surface(explicit_cloud) == "CLOUD"
    assert resolve_knowledge_workspace_mode(explicit_cloud) == "LOCAL_SANDBOX"


def test_remote_portal_defaults_to_cloud_formal_and_blocks_header_auth(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        knowledge_in_process=False,
        auth_mode="HEADER",
        relaxed_workflow=True,
    )
    gate = evaluate_knowledge_workspace_gate(settings)
    assert gate.workspace_mode == "CLOUD_FORMAL"
    assert gate.cloud_formal_writes_allowed is False
    assert "auth_mode_not_entra" in gate.block_reasons
    assert "relaxed_workflow" in gate.block_reasons
    assert "formal_writes_flag_disabled" in gate.block_reasons

    with pytest.raises(KnowledgeBridgeError) as exc_info:
        assert_formal_cloud_write_allowed(
            settings=settings,
            capability="knowledge.publish",
            correlation_id="corr-1",
        )
    assert exc_info.value.code == "KNOWLEDGE_CLOUD_FORMAL_WRITES_BLOCKED"


def test_cloud_formal_writes_require_entra_and_explicit_flag(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        knowledge_in_process=False,
        knowledge_workspace_mode="CLOUD_FORMAL",
        auth_mode="ENTRA",
        relaxed_workflow=False,
        entra_tenant_id="tenant",
        entra_client_id="client",
        knowledge_cloud_formal_writes_enabled=True,
    )
    gate = evaluate_knowledge_workspace_gate(settings)
    assert gate.cloud_formal_writes_allowed is True
    assert_formal_cloud_write_allowed(
        settings=settings,
        capability="knowledge.publish",
        correlation_id="corr-2",
    )


def test_formal_caps_stripped_when_cloud_blocked(tmp_path: Path) -> None:
    actor = ActorContext(
        user_id="admin",
        display_name="Admin",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("IT",),
        tenant_id="t1",
    )
    settings = _settings(tmp_path, knowledge_in_process=False, auth_mode="HEADER")
    caps = filter_knowledge_capabilities_for_workspace(
        knowledge_capabilities_for(actor),
        settings,
    )
    assert FORMAL_CLOUD_WRITE_CAPABILITIES.isdisjoint(caps)
    assert "knowledge.read" in caps


def test_local_sandbox_keeps_publish_capability(tmp_path: Path) -> None:
    actor = ActorContext(
        user_id="admin",
        display_name="Admin",
        role="KNOWLEDGE_ADMIN",
        owner_unit_ids=("IT",),
        tenant_id="t1",
    )
    settings = _settings(tmp_path, knowledge_in_process=True, auth_mode="HEADER")
    caps = filter_knowledge_capabilities_for_workspace(
        knowledge_capabilities_for(actor),
        settings,
    )
    assert "knowledge.publish" in caps


def test_capabilities_endpoint_exposes_workspace_banner_fields(tmp_path: Path) -> None:
    settings = _settings(tmp_path, knowledge_in_process=True)
    app = create_app(settings)
    client = TestClient(app)
    response = client.get(
        "/api/capabilities",
        headers={
            "X-Backoffice-User-Id": "u1",
            "X-Backoffice-User-Name": "User",
            "X-Backoffice-Role": "SYSTEM_ADMIN",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["knowledgeWorkspaceMode"] == "LOCAL_SANDBOX"
    assert payload["cloudFormalWritesAllowed"] is False
    assert payload["cloudFormalWriteBlockReasons"] == ["local_sandbox_workspace"]
    assert payload["knowledgeWorkspaceSwitchAllowed"] is True
    assert payload["authMode"] == "HEADER"
    assert payload["relaxedWorkflow"] is True
    assert payload["knowledgeInProcess"] is True
    assert payload["consoleSurface"] == "LOCAL"


def test_capabilities_exposes_cloud_surface_without_cloud_formal_workspace(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        knowledge_in_process=False,
        console_surface="CLOUD",
        knowledge_workspace_mode="LOCAL_SANDBOX",
    )
    app = create_app(settings)
    client = TestClient(app)
    response = client.get(
        "/api/capabilities",
        headers={
            "X-Backoffice-User-Id": "u1",
            "X-Backoffice-User-Name": "User",
            "X-Backoffice-Role": "SYSTEM_ADMIN",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["knowledgeInProcess"] is False
    assert payload["consoleSurface"] == "CLOUD"
    assert payload["knowledgeWorkspaceMode"] == "LOCAL_SANDBOX"
    assert payload["cloudFormalWritesAllowed"] is False
    assert "knowledge.publish" in payload["knowledgeCapabilities"]


def test_knowledge_workspace_switch_does_not_unlock_formal_writes(
    tmp_path: Path,
) -> None:
    from ai_ops_backoffice.knowledge_bridge.formal_write_gate import (
        apply_knowledge_workspace_mode,
    )

    settings = _settings(tmp_path, knowledge_in_process=True, auth_mode="HEADER")
    app = create_app(settings)
    client = TestClient(app)
    headers = {
        "X-Backoffice-User-Id": "admin",
        "X-Backoffice-User-Name": "Admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }

    switched = client.put(
        "/api/knowledge-workspace",
        headers=headers,
        json={"knowledgeWorkspaceMode": "CLOUD_FORMAL", "reason": "test"},
    )
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["knowledgeWorkspaceMode"] == "CLOUD_FORMAL"
    assert body["cloudFormalWritesAllowed"] is False
    assert body["knowledgeWorkspaceOverrideActive"] is True
    assert "auth_mode_not_entra" in body["cloudFormalWriteBlockReasons"]
    assert body["cloudFormalWriteBlockReasonLabels"]

    caps = client.get("/api/capabilities", headers=headers)
    assert caps.json()["knowledgeWorkspaceMode"] == "CLOUD_FORMAL"
    assert "knowledge.publish" not in caps.json()["knowledgeCapabilities"]

    # Viewer cannot switch.
    denied = client.put(
        "/api/knowledge-workspace",
        headers={
            "X-Backoffice-User-Id": "viewer",
            "X-Backoffice-User-Name": "Viewer",
            "X-Backoffice-Role": "VIEWER",
        },
        json={"knowledgeWorkspaceMode": "LOCAL_SANDBOX"},
    )
    assert denied.status_code == 403

    apply_knowledge_workspace_mode(settings, "LOCAL_SANDBOX")
    local = client.put(
        "/api/knowledge-workspace",
        headers=headers,
        json={"knowledgeWorkspaceMode": "LOCAL_SANDBOX"},
    )
    assert local.status_code == 200
    assert local.json()["knowledgeWorkspaceMode"] == "LOCAL_SANDBOX"


def test_workspace_mode_override_survives_process_restart(tmp_path: Path) -> None:
    """PUT persists under ops/; create_app reloads override over env bootstrap."""
    from ai_ops_backoffice.knowledge_bridge.knowledge_workspace_store import (
        knowledge_workspace_override_path,
    )

    settings = _settings(
        tmp_path,
        knowledge_in_process=True,
        knowledge_workspace_mode=None,
        auth_mode="HEADER",
        relaxed_workflow=True,
    )
    headers = {
        "X-Backoffice-User-Id": "admin",
        "X-Backoffice-User-Name": "Admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    with TestClient(create_app(settings)) as client:
        switched = client.put(
            "/api/knowledge-workspace",
            headers=headers,
            json={
                "knowledgeWorkspaceMode": "CLOUD_FORMAL",
                "reason": "persist-across-restart",
            },
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["knowledgeWorkspaceMode"] == "CLOUD_FORMAL"
        assert switched.json()["cloudFormalWritesAllowed"] is False

    override_path = knowledge_workspace_override_path(settings)
    assert override_path.is_file()
    assert '"overrideMode": "CLOUD_FORMAL"' in override_path.read_text(encoding="utf-8")

    # Fresh settings object: env/bootstrap would be LOCAL_SANDBOX (in-process).
    restarted = _settings(
        tmp_path,
        knowledge_in_process=True,
        knowledge_workspace_mode="LOCAL_SANDBOX",
        auth_mode="HEADER",
        relaxed_workflow=True,
    )
    assert resolve_knowledge_workspace_mode(restarted) == "LOCAL_SANDBOX"
    with TestClient(create_app(restarted)) as client:
        gate = client.get("/api/knowledge-workspace", headers=headers)
        assert gate.status_code == 200
        body = gate.json()
        assert body["knowledgeWorkspaceMode"] == "CLOUD_FORMAL"
        assert body["knowledgeWorkspaceOverrideActive"] is True
        assert body["knowledgeWorkspaceModeSource"] == "override"
        assert body["cloudFormalWritesAllowed"] is False
        assert "auth_mode_not_entra" in body["cloudFormalWriteBlockReasons"]
        assert "knowledge.publish" not in client.get(
            "/api/capabilities", headers=headers
        ).json()["knowledgeCapabilities"]


def test_corrupt_workspace_override_falls_back_to_env_bootstrap(
    tmp_path: Path,
) -> None:
    from ai_ops_backoffice.knowledge_bridge.knowledge_workspace_store import (
        knowledge_workspace_override_path,
    )

    settings = _settings(
        tmp_path,
        knowledge_in_process=True,
        knowledge_workspace_mode="LOCAL_SANDBOX",
    )
    path = knowledge_workspace_override_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    with TestClient(create_app(settings)) as client:
        body = client.get(
            "/api/knowledge-workspace",
            headers={
                "X-Backoffice-User-Id": "admin",
                "X-Backoffice-User-Name": "Admin",
                "X-Backoffice-Role": "SYSTEM_ADMIN",
            },
        ).json()
        assert body["knowledgeWorkspaceMode"] == "LOCAL_SANDBOX"
        assert body["knowledgeWorkspaceOverrideActive"] is False


def test_workspace_mode_reset_restores_env_default(tmp_path: Path) -> None:
    from ai_ops_backoffice.knowledge_bridge.knowledge_workspace_store import (
        knowledge_workspace_override_path,
    )

    settings = _settings(
        tmp_path,
        knowledge_in_process=True,
        knowledge_workspace_mode="LOCAL_SANDBOX",
        knowledge_workspace_mode_default="LOCAL_SANDBOX",
        auth_mode="HEADER",
    )
    headers = {
        "X-Backoffice-User-Id": "admin",
        "X-Backoffice-User-Name": "Admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
    }
    with TestClient(create_app(settings)) as client:
        switched = client.put(
            "/api/knowledge-workspace",
            headers=headers,
            json={"knowledgeWorkspaceMode": "CLOUD_FORMAL"},
        )
        assert switched.status_code == 200
        assert switched.json()["knowledgeWorkspaceOverrideActive"] is True

        reset = client.delete("/api/knowledge-workspace", headers=headers)
        assert reset.status_code == 200, reset.text
        body = reset.json()
        assert body["knowledgeWorkspaceMode"] == "LOCAL_SANDBOX"
        assert body["knowledgeWorkspaceOverrideActive"] is False
        assert body["knowledgeWorkspaceModeSource"] in {"env", "inferred"}

    assert not knowledge_workspace_override_path(settings).is_file()

    restarted = _settings(
        tmp_path,
        knowledge_in_process=True,
        knowledge_workspace_mode="LOCAL_SANDBOX",
        knowledge_workspace_mode_default="LOCAL_SANDBOX",
    )
    with TestClient(create_app(restarted)) as client:
        body = client.get("/api/knowledge-workspace", headers=headers).json()
        assert body["knowledgeWorkspaceMode"] == "LOCAL_SANDBOX"
        assert body["knowledgeWorkspaceOverrideActive"] is False


def test_cloud_workspace_proxy_rejects_publish_without_formal_identity(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        knowledge_in_process=False,
        knowledge_workspace_mode="CLOUD_FORMAL",
        auth_mode="HEADER",
        relaxed_workflow=True,
    )
    app = create_app(settings)
    client = TestClient(app)
    response = client.post(
        "/api/knowledge/documents/doc-1/publish",
        headers={
            "X-Backoffice-User-Id": "u1",
            "X-Backoffice-User-Name": "User",
            "X-Backoffice-Role": "SYSTEM_ADMIN",
            "Content-Type": "application/json",
        },
        json={},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "KNOWLEDGE_CLOUD_FORMAL_WRITES_BLOCKED"
