from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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


def _headers(role: str, user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_faq_performance_period_switching_consistency(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    query_service = BackofficeQueryService(settings)
    actor = ActorContext("tester", "Tester", "SYSTEM_ADMIN", ("IT Service Desk",))

    now = datetime.now(timezone.utc)
    ev_today = OperationalEvent(
        event_id="ev-today",
        event_type="faq.answered",
        occurred_at=now,
        conversation_id="conv-today",
        turn_id="turn-1",
        correlation_id="corr-1",
        channel_scope="channel",
        actor_ref="user-1",
        payload={"faqKey": "faq.vpn.setup", "faqId": "faq-vpn", "faqVersionId": "v2"},
    )
    ev_10d_ago = OperationalEvent(
        event_id="ev-10d",
        event_type="faq.answered",
        occurred_at=now - timedelta(days=10),
        conversation_id="conv-10d",
        turn_id="turn-1",
        correlation_id="corr-2",
        channel_scope="channel",
        actor_ref="user-2",
        payload={"faqKey": "faq.vpn.setup", "faqId": "faq-vpn", "faqVersionId": "v1"},
    )
    ev_45d_ago = OperationalEvent(
        event_id="ev-45d",
        event_type="faq.answered",
        occurred_at=now - timedelta(days=45),
        conversation_id="conv-45d",
        turn_id="turn-1",
        correlation_id="corr-3",
        channel_scope="channel",
        actor_ref="user-3",
        payload={"faqKey": "faq.vpn.setup", "faqId": "faq-vpn", "faqVersionId": "v1"},
    )

    async def _mock_events(**kwargs: Any) -> list[OperationalEvent]:
        return [ev_today, ev_10d_ago, ev_45d_ago]

    query_service._events = _mock_events  # type: ignore[method-assign]

    perf_all = asyncio.run(query_service.faq_performance(actor, faq_key="faq.vpn.setup"))
    assert perf_all["totalHitCount"] == 3
    assert perf_all["rangeHitCount"] == 3
    assert len(perf_all["recentHits"]) == 3

    perf_7d = asyncio.run(query_service.faq_performance(actor, faq_key="faq.vpn.setup", days=7))
    assert perf_7d["totalHitCount"] == 3
    assert perf_7d["rangeHitCount"] == 1
    assert len(perf_7d["recentHits"]) == 1
    assert perf_7d["recentHits"][0]["conversationId"] == "conv-today"
    assert len(perf_7d["byVersion"]) == 1
    assert perf_7d["byVersion"][0]["versionId"] == "v2"

    perf_30d = asyncio.run(query_service.faq_performance(actor, faq_key="faq.vpn.setup", days=30))
    assert perf_30d["totalHitCount"] == 3
    assert perf_30d["rangeHitCount"] == 2
    assert len(perf_30d["recentHits"]) == 2
    assert {h["conversationId"] for h in perf_30d["recentHits"]} == {"conv-today", "conv-10d"}

    start_str = (now - timedelta(days=15)).date().isoformat()
    end_str = (now - timedelta(days=5)).date().isoformat()
    perf_custom = asyncio.run(
        query_service.faq_performance(
            actor,
            faq_key="faq.vpn.setup",
            start_date=start_str,
            end_date=end_str,
        )
    )
    assert perf_custom["rangeHitCount"] == 1
    assert perf_custom["recentHits"][0]["conversationId"] == "conv-10d"


def test_knowledge_export_forwards_all_filter_fields(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    admin_hdrs = _headers("SYSTEM_ADMIN")

    document = {
        "document_id": "vpn-setup-guide",
        "title": "VPN Setup Guide",
        "owner_unit_id": "IT Service Desk",
        "status": "PUBLISHED",
    }
    mock_portal = MagicMock()
    mock_portal.__aenter__ = AsyncMock(return_value=mock_portal)
    mock_portal.__aexit__ = AsyncMock(return_value=False)

    def _resp(payload: dict) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = payload
        return r

    mock_portal.get = AsyncMock(
        side_effect=[
            _resp({"items": [document], "total": 1}),
            _resp({"items": []}),
            _resp({
                "document": document,
                "published_version": {
                    "source_type": "MARKDOWN_PASTE",
                    "parse_preview": {"segments": []},
                },
            }),
        ]
    )

    with patch("ai_ops_backoffice.services.query_service.httpx.AsyncClient", return_value=mock_portal):
        payload = {
            "export_type": "knowledge_performance",
            "reason": "Quarterly audit and performance check",
            "days": 90,
            "export_format": "json",
            "status": "PUBLISHED",
            "owner_unit_id": "IT Service Desk",
            "format_type": "MARKDOWN",
            "query": "vpn setup guide",
        }
        create_res = client.post("/api/exports", json=payload, headers=admin_hdrs)
        assert create_res.status_code == 200, create_res.text
        job_data = create_res.json()
        job_id = job_data["jobId"]
        assert job_id

        # Poll until COMPLETED
        completed = None
        for _ in range(40):
            completed = client.get(f"/api/exports/{job_id}", headers=admin_hdrs)
            assert completed.status_code == 200
            if completed.json()["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(0.05)
        assert completed is not None
        assert completed.json()["status"] == "COMPLETED"

    download_res = client.get(f"/api/exports/{job_id}/download", headers=admin_hdrs)
    assert download_res.status_code == 200
    result_json = download_res.json()

    meta = result_json.get("exportMetadata", {})
    assert meta.get("exportType") == "knowledge_performance"
    query_filters = meta.get("queryFilters", {})
    assert query_filters.get("status") == "PUBLISHED"
    assert query_filters.get("ownerUnitId") == "IT Service Desk"
    assert query_filters.get("formatType") == "MARKDOWN"
    assert query_filters.get("query") == "vpn setup guide"


def test_sync_jobs_scope_selection_and_validation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    admin_hdrs = _headers("SYSTEM_ADMIN")

    all_res = client.post(
        "/api/sync-jobs",
        json={
            "scope_type": "ALL",
            "scope_ids": [],
            "reason": "Routine full sync",
        },
        headers=admin_hdrs,
    )
    assert all_res.status_code == 200
    assert all_res.json()["job"]["scope_type"] == "ALL"

    faq_fail = client.post(
        "/api/sync-jobs",
        json={
            "scope_type": "FAQ",
            "scope_ids": [],
            "reason": "Test empty FAQ sync",
        },
        headers=admin_hdrs,
    )
    assert faq_fail.status_code in {400, 422}

    doc_fail = client.post(
        "/api/sync-jobs",
        json={
            "scope_type": "DOCUMENT",
            "scope_ids": [],
            "reason": "Test empty DOCUMENT sync",
        },
        headers=admin_hdrs,
    )
    assert doc_fail.status_code in {400, 422}
