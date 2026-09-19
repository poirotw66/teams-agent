"""Tests verifying Milestone 3 Nested Immutable Configuration slices."""

from __future__ import annotations

from pathlib import Path

from ai_ops_backoffice.settings import (
    AuthSettings,
    BackofficeSettings,
    ExportJobSettings,
    KnowledgeBridgeSettings,
    NotificationSettings,
)


def test_settings_slices_extraction(tmp_path: Path):
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="test-sec-token",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id="tenant-123",
        entra_client_id="client-456",
        teams_webhook_url="https://webhook.teams.local",
    )

    auth_slice = settings.auth
    assert isinstance(auth_slice, AuthSettings)
    assert auth_slice.auth_mode == "HEADER"
    assert auth_slice.service_token == "test-sec-token"
    assert auth_slice.entra_tenant_id == "tenant-123"

    bridge_slice = settings.knowledge_bridge
    assert isinstance(bridge_slice, KnowledgeBridgeSettings)
    assert bridge_slice.portal_url == "http://127.0.0.1:8091"
    assert bridge_slice.enabled is True

    notif_slice = settings.notifications
    assert isinstance(notif_slice, NotificationSettings)
    assert notif_slice.teams_webhook_url == "https://webhook.teams.local"

    export_slice = settings.export_jobs_config
    assert isinstance(export_slice, ExportJobSettings)
    assert export_slice.store_mode == "FILE"
