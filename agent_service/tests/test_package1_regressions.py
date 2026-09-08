from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.services.query_service import BackofficeQueryService
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


def headers(role: str, user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_faq_performance_period_and_timezone(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    query_service = BackofficeQueryService(settings)
    actor = ActorContext("tester", "Tester", "SYSTEM_ADMIN", ("IT Service Desk",))

    now = datetime.now(timezone.utc)
    ev1 = OperationalEvent(
        event_id="ev-1",
        event_type="faq.answered",
        occurred_at=now,
        conversation_id="conv-1",
        turn_id="turn-1",
        correlation_id="corr-1",
        channel_scope="channel",
        actor_ref="user-1",
        payload={"faqKey": "faq.vpn.general", "faqId": "faq-101", "faqVersionId": "v1"},
    )
    async def _mock_events(**kwargs):
        return [ev1]
    query_service._events = _mock_events

    result_preset = asyncio.run(
        query_service.faq_performance(
            actor,
            faq_key="faq.vpn.general",
            preset="LAST_30_DAYS",
        )
    )
    assert result_preset["faqKey"] == "faq.vpn.general"
    assert result_preset["totalHitCount"] == 1
    assert result_preset["todayHitCount"] == 1
    assert len(result_preset["byDay"]) == 1

    result_days = asyncio.run(
        query_service.faq_performance(
            actor,
            faq_key="faq.vpn.general",
            days=7,
        )
    )
    assert result_days["rangeHitCount"] == 1


def test_sync_routes_faq_scope_injection(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    admin_hdrs = headers("SYSTEM_ADMIN")

    res = client.post(
        "/api/sync-jobs",
        json={
            "scope_type": "FAQ",
            "scope_ids": ["faq-non-existent"],
            "reason": "sync test",
        },
        headers=admin_hdrs,
    )
    assert res.status_code == 404


def test_quality_case_observation_refresh_route(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    admin_hdrs = headers("SYSTEM_ADMIN")

    res = client.post(
        "/api/quality-cases/case-not-found/observation/refresh",
        json={"expected_etag": 1},
        headers=admin_hdrs,
    )
    assert res.status_code == 404
