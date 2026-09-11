"""Verification test suite for BU Priority 4 requirements.

Covers:
- REQ-001: 對話量統計 (日/週/月趨勢、模型與 Issue 篩選)
- REQ-005: FAQ 命中統計 (總命中、當月、當週、當日命中次數與追溯)
- REQ-011: Issue Dashboard (支援最近6個月、1個月、1週、1日檢視及匯出一致性)
- REQ-012: Issue 路由來源分析 (FAQ／RAG attribution、Issue／Route 篩選)
- REQ-027: 全域搜尋與篩選 (FAQ、文件、Issue、對話關鍵字搜尋與分類篩選)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent
from ai_ops_backoffice.api import create_app as create_backoffice_app
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.settings import BackofficeSettings


def _backoffice_settings(tmp_path: Path, **overrides) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    params = {
        "host": "127.0.0.1",
        "port": 8092,
        "service_token": "",
        "auth_mode": "HEADER",
        "ops_store_mode": "FILE",
        "ops_store_path": tmp_path / "events",
        "ops_taxonomy_path": data_dir / "ops" / "issue_taxonomy_v1.json",
        "ops_metrics_path": data_dir / "ops" / "metrics_definitions_v1.json",
        "ops_classification_rules_path": data_dir / "ops" / "issue_classification_rules.json",
        "ops_audit_store_mode": "FILE",
        "knowledge_portal_url": "http://127.0.0.1:8091",
        "sync_adapter_url": "http://127.0.0.1:8091",
        "agent_api_url": "http://127.0.0.1:8000",
        "adapter_api_url": "http://127.0.0.1:3978",
        "ticket_service_url": None,
        "default_owner_unit_id": "IT Service Desk",
        "entra_tenant_id": None,
        "entra_client_id": None,
        "budget_store_path": tmp_path / "budgets.json",
        "faq_store_path": tmp_path / "faqs.json",
        "export_content_path": tmp_path / "exports",
        **overrides,
    }
    return BackofficeSettings(**params)


def backoffice_headers(role: str = "SYSTEM_ADMIN", user_id: str = "analyst-p4@corp.local") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id,
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def _event(
    *,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    conversation_id: str,
    correlation_id: str,
    turn_id: str,
    actor_ref: str = "user-1",
    issue_type_id: str | None = None,
    issue_occurrence_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> OperationalEvent:
    return OperationalEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        environment="test",
        channel_scope="personal",
        actor_ref=actor_ref,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        turn_id=turn_id,
        issue_type_id=issue_type_id,
        issue_occurrence_id=issue_occurrence_id,
        payload=dict(payload or {}),
        retention_expires_at=occurred_at + timedelta(days=365),
    )


# =========================================================================
# REQ-001: 對話量統計 (日/週/月趨勢、模型與 Issue 篩選)
# =========================================================================

@pytest.mark.asyncio
async def test_conversation_volume_daily_weekly_monthly_trends(tmp_path: Path) -> None:
    """REQ-001: Operations summary returns day/week/month trends, supporting model and issue filtering."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)

    # Seed events over multiple days
    # Day 1: 2 turns with gemini-2.5-flash and vpn.connection_failed
    # Day 2: 1 turn with gemini-2.5-pro and network.internet_slow
    # Keep the ten-minute second turn on the same UTC calendar day even when
    # the suite runs close to midnight; the assertion is about two populated
    # daily buckets, not a midnight boundary.
    day1 = now - timedelta(days=5, hours=1)
    day2 = now - timedelta(days=1)

    events = [
        # Day 1 - Conv 1 Turn 1
        _event(
            event_id="d1:t1:received",
            event_type="turn.received",
            occurred_at=day1,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id="turn-1",
            actor_ref="alice@corp.local",
            issue_type_id="vpn.connection_failed",
            payload={"messageMasked": "VPN issue 1"},
        ),
        _event(
            event_id="d1:t1:issue",
            event_type="issue.extracted",
            occurred_at=day1,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id="turn-1",
            issue_type_id="vpn.connection_failed",
        ),
        _event(
            event_id="d1:t1:usage",
            event_type="usage.recorded",
            occurred_at=day1,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id="turn-1",
            payload={"model": "gemini-2.5-flash", "totalTokens": 100, "estimatedCostUsd": 0.001, "costComplete": True},
        ),
        # Day 1 - Conv 1 Turn 2
        _event(
            event_id="d1:t2:received",
            event_type="turn.received",
            occurred_at=day1 + timedelta(minutes=10),
            conversation_id="conv-1",
            correlation_id="corr-2",
            turn_id="turn-2",
            actor_ref="alice@corp.local",
            issue_type_id="vpn.connection_failed",
            payload={"messageMasked": "VPN issue 2"},
        ),
        _event(
            event_id="d1:t2:usage",
            event_type="usage.recorded",
            occurred_at=day1 + timedelta(minutes=10),
            conversation_id="conv-1",
            correlation_id="corr-2",
            turn_id="turn-2",
            payload={"model": "gemini-2.5-flash", "totalTokens": 150, "estimatedCostUsd": 0.0015, "costComplete": True},
        ),
        # Day 2 - Conv 2 Turn 1
        _event(
            event_id="d2:t1:received",
            event_type="turn.received",
            occurred_at=day2,
            conversation_id="conv-2",
            correlation_id="corr-3",
            turn_id="turn-3",
            actor_ref="bob@corp.local",
            issue_type_id="network.internet_slow",
            payload={"messageMasked": "Internet slow"},
        ),
        _event(
            event_id="d2:t1:issue",
            event_type="issue.extracted",
            occurred_at=day2,
            conversation_id="conv-2",
            correlation_id="corr-3",
            turn_id="turn-3",
            issue_type_id="network.internet_slow",
        ),
        _event(
            event_id="d2:t1:usage",
            event_type="usage.recorded",
            occurred_at=day2,
            conversation_id="conv-2",
            correlation_id="corr-3",
            turn_id="turn-3",
            payload={"model": "gemini-2.5-pro", "totalTokens": 500, "estimatedCostUsd": 0.01, "costComplete": True},
        ),
    ]

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    # 1. Query daily trends (default DAY interval)
    resp = client.get("/api/operations/summary?days=7&interval=DAY", headers=backoffice_headers())
    assert resp.status_code == 200
    data = resp.json()

    assert data["conversationCount"] == 2
    assert data["turnCount"] == 3
    assert data["activeUserCount"] == 2
    assert "trends" in data
    trends = data["trends"]
    assert len(trends) == 2  # Day 1 and Day 2

    d1_bucket = next(t for t in trends if t["period"] == day1.date().isoformat())
    assert d1_bucket["conversationCount"] == 1
    assert d1_bucket["turnCount"] == 2
    assert d1_bucket["activeUserCount"] == 1
    assert d1_bucket["totalTokens"] == 250

    d2_bucket = next(t for t in trends if t["period"] == day2.date().isoformat())
    assert d2_bucket["conversationCount"] == 1
    assert d2_bucket["turnCount"] == 1
    assert d2_bucket["activeUserCount"] == 1
    assert d2_bucket["totalTokens"] == 500

    # 2. Filter by model: gemini-2.5-pro
    pro_resp = client.get(
        "/api/operations/summary?days=7&model=gemini-2.5-pro",
        headers=backoffice_headers(),
    )
    assert pro_resp.status_code == 200
    pro_data = pro_resp.json()
    assert pro_data["turnCount"] == 1
    assert pro_data["conversationCount"] == 1
    assert pro_data["totalTokens"] == 500

    # 3. Filter by issue_type_id: vpn.connection_failed
    vpn_resp = client.get(
        "/api/operations/summary?days=7&issue_type_id=vpn.connection_failed",
        headers=backoffice_headers(),
    )
    assert vpn_resp.status_code == 200
    vpn_data = vpn_resp.json()
    assert vpn_data["turnCount"] == 2
    assert vpn_data["conversationCount"] == 1

    # 4. Weekly / monthly trend buckets remain available for dashboard controls
    week_resp = client.get(
        "/api/operations/summary?days=7&interval=WEEK",
        headers=backoffice_headers(),
    )
    assert week_resp.status_code == 200
    week_data = week_resp.json()
    assert week_data["interval"] == "WEEK"
    assert week_data["conversationCount"] == 2
    assert len(week_data["trends"]) >= 1

    month_resp = client.get(
        "/api/operations/summary?days=7&interval=MONTH",
        headers=backoffice_headers(),
    )
    assert month_resp.status_code == 200
    month_data = month_resp.json()
    assert month_data["interval"] == "MONTH"
    assert month_data["conversationCount"] == 2
    assert len(month_data["trends"]) >= 1

    # 5. One-year query window is accepted for REQ-001 retention alignment
    year_resp = client.get(
        "/api/operations/summary?preset=1y&interval=MONTH",
        headers=backoffice_headers(),
    )
    assert year_resp.status_code == 200
    year_data = year_resp.json()
    assert year_data["periodPreset"] == "1y"
    assert year_data["periodDays"] == 365
    assert year_data["interval"] == "MONTH"
    assert year_data["conversationCount"] == 2


# =========================================================================
# REQ-005: FAQ 命中統計 (總命中、當月、當週、當日命中次數與追溯)
# =========================================================================

@pytest.mark.asyncio
async def test_faq_today_this_week_this_month_hit_counts(tmp_path: Path) -> None:
    """REQ-005: Verify FAQ performance calculates today, this week, this month, and total hit counts."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    faq_payload = {
        "faq_key": "faq-vpn-setup",
        "question": "如何安裝設定公司 VPN 用戶端？",
        "answer": "請從 IT Portal 下載 Cisco AnyConnect 安裝檔。",
        "category": "網路與連線",
        "keywords": ["VPN", "AnyConnect", "遠端辦公"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "it-support@corp.local",
        "issue_type_ids": ["vpn.connection_failed"],
        "audience_type": "ALL",
        "audience_group_ids": [],
    }
    faq_created = client.post("/api/faqs", json=faq_payload, headers=backoffice_headers())
    assert faq_created.status_code == 200
    faq_id = faq_created.json()["faq"]["faq_id"]

    events = [
        # Today hit
        _event(
            event_id="faq-hit-today",
            event_type="faq.answered",
            occurred_at=now - timedelta(minutes=30),
            conversation_id="conv-faq-1",
            correlation_id="corr-faq-1",
            turn_id="turn-faq-1",
            payload={"faqKey": "faq-vpn-setup", "faqId": faq_id, "faqVersionId": "v1"},
        ),
        # Hit 1 day ago
        _event(
            event_id="faq-hit-2",
            event_type="faq.answered",
            occurred_at=now - timedelta(days=1),
            conversation_id="conv-faq-2",
            correlation_id="corr-faq-2",
            turn_id="turn-faq-2",
            payload={"faqKey": "faq-vpn-setup", "faqId": faq_id, "faqVersionId": "v1"},
        ),
    ]

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    # Query FAQ performance
    resp = client.get(f"/api/faqs/{faq_id}/performance", headers=backoffice_headers())
    assert resp.status_code == 200
    perf = resp.json()

    assert perf["faqKey"] == "faq-vpn-setup"
    assert perf["totalHitCount"] == 2
    assert perf["todayHitCount"] == 1
    assert perf["thisWeekHitCount"] >= 1
    assert perf["thisMonthHitCount"] >= 1
    assert "recentHits" in perf
    assert len(perf["recentHits"]) == 2
    assert perf["recentHits"][0]["faqId"] == faq_id
    assert isinstance(perf.get("byDay"), list)
    assert isinstance(perf.get("byWeek"), list)
    assert isinstance(perf.get("byMonth"), list)

    # Test category filtering and keyword search in list_faqs
    list_resp = client.get("/api/faqs?category=網路與連線", headers=backoffice_headers())
    assert list_resp.status_code == 200
    assert len(list_resp.json()["items"]) == 1

    owner_resp = client.get(
        "/api/faqs?owner_unit_id=IT Service Desk", headers=backoffice_headers()
    )
    assert owner_resp.status_code == 200
    assert len(owner_resp.json()["items"]) == 1

    keyword_resp = client.get("/api/faqs?keyword=AnyConnect", headers=backoffice_headers())
    assert keyword_resp.status_code == 200
    assert len(keyword_resp.json()["items"]) == 1

    search_resp = client.get("/api/faqs?query=AnyConnect", headers=backoffice_headers())
    assert search_resp.status_code == 200
    assert len(search_resp.json()["items"]) == 1


# =========================================================================
# REQ-011: Issue Dashboard 期間檢視與匯出一致性
# =========================================================================

@pytest.mark.asyncio
async def test_issue_dashboard_presets_and_export_consistency(tmp_path: Path) -> None:
    """REQ-011: Issue summary supports 1d/7d/30d/180d presets and export consistency."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)

    events = [
        _event(
            event_id="iss-1",
            event_type="issue.extracted",
            occurred_at=now - timedelta(hours=2),
            conversation_id="c1",
            correlation_id="cor1",
            turn_id="t1",
            issue_type_id="vpn.connection_failed",
        ),
        _event(
            event_id="iss-2",
            event_type="issue.extracted",
            occurred_at=now - timedelta(days=15),
            conversation_id="c2",
            correlation_id="cor2",
            turn_id="t2",
            issue_type_id="network.internet_slow",
        ),
    ]

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    # 1. 1d preset should only include today's issue
    resp_1d = client.get("/api/issues/summary?preset=1d", headers=backoffice_headers())
    assert resp_1d.status_code == 200
    items_1d = resp_1d.json()["items"]
    assert len(items_1d) == 1
    assert items_1d[0]["issueTypeId"] == "vpn.connection_failed"

    # 2. 30d preset includes both
    resp_30d = client.get("/api/issues/summary?preset=30d", headers=backoffice_headers())
    assert resp_30d.status_code == 200
    assert len(resp_30d.json()["items"]) == 2

    # 3. Keyword filtering in issues_summary
    query_resp = client.get("/api/issues/summary?query=VPN", headers=backoffice_headers())
    assert query_resp.status_code == 200
    q_items = query_resp.json()["items"]
    assert len(q_items) == 1
    assert q_items[0]["issueTypeId"] == "vpn.connection_failed"

    # 4. Consistent Export: export job with preset=1d
    export_resp = client.post(
        "/api/exports",
        headers=backoffice_headers(),
        json={
            "export_type": "issues_summary",
            "reason": "Test consistency",
            "preset": "1d",
            "days": 1,
            "export_format": "json",
        },
    )
    assert export_resp.status_code == 200
    job_id = export_resp.json()["jobId"]

    # Download export result
    dl_resp = client.get(f"/api/exports/{job_id}/download", headers=backoffice_headers())
    assert dl_resp.status_code == 200
    payload = json.loads(dl_resp.text)
    assert payload["exportMetadata"]["exportType"] == "issues_summary"
    assert len(payload["data"]["items"]) == 1
    assert payload["data"]["items"][0]["issueTypeId"] == "vpn.connection_failed"

    # 5. Query filter also scopes trends
    trends = query_resp.json()["trends"]
    for day in trends:
        assert all(item["issueTypeId"] == "vpn.connection_failed" for item in day["counts"])


# =========================================================================
# REQ-012: Issue 路由來源分析（FAQ／RAG attribution）
# =========================================================================

@pytest.mark.asyncio
async def test_issue_route_source_analysis_faq_and_documents(tmp_path: Path) -> None:
    """REQ-012: Route summary exposes FAQ ID / Document ID attribution and filters."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)
    occurrence = "turn-faq:issue:1"
    events = [
        _event(
            event_id="route-faq-selected",
            event_type="route.selected",
            occurred_at=now,
            conversation_id="c-faq",
            correlation_id="cor-faq",
            turn_id="turn-faq",
            issue_type_id="vpn.connection_failed",
            issue_occurrence_id=occurrence,
            payload={"route": "FAQ"},
        ),
        _event(
            event_id="faq-answered-1",
            event_type="faq.answered",
            occurred_at=now,
            conversation_id="c-faq",
            correlation_id="cor-faq",
            turn_id="turn-faq",
            issue_type_id="vpn.connection_failed",
            issue_occurrence_id=occurrence,
            payload={
                "faqId": "faq-id-vpn-001",
                "faqKey": "faq-vpn-setup",
                "resultType": "FAQ_ANSWERED",
            },
        ),
        _event(
            event_id="route-rag-selected",
            event_type="route.selected",
            occurred_at=now,
            conversation_id="c-rag",
            correlation_id="cor-rag",
            turn_id="turn-rag",
            issue_type_id="network.internet_slow",
            issue_occurrence_id="turn-rag:issue:1",
            payload={"route": "KNOWLEDGE"},
        ),
        _event(
            event_id="knowledge-answered-1",
            event_type="knowledge.answered",
            occurred_at=now,
            conversation_id="c-rag",
            correlation_id="cor-rag",
            turn_id="turn-rag",
            issue_type_id="network.internet_slow",
            issue_occurrence_id="turn-rag:issue:1",
            payload={
                "documentId": "doc-network-slow",
                "versionId": "v3",
                "releaseId": "rel-1",
                "resultType": "KNOWLEDGE_ANSWERED",
            },
        ),
    ]

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    all_routes = client.get("/api/routes/summary?preset=30d", headers=backoffice_headers())
    assert all_routes.status_code == 200
    body = all_routes.json()
    by_route = {item["route"]: item for item in body["routeDistribution"]}
    assert by_route["FAQ"]["attribution"]["faqIds"] == [{"id": "faq-id-vpn-001", "count": 1}]
    assert by_route["FAQ"]["attribution"]["faqKeys"] == [{"id": "faq-vpn-setup", "count": 1}]
    assert by_route["KNOWLEDGE"]["attribution"]["documentIds"] == [
        {"id": "doc-network-slow", "count": 1}
    ]

    faq_only = client.get(
        "/api/routes/summary?preset=30d&route=FAQ&issue_type_id=vpn.connection_failed",
        headers=backoffice_headers(),
    )
    assert faq_only.status_code == 200
    faq_body = faq_only.json()
    assert len(faq_body["routeDistribution"]) == 1
    assert faq_body["routeDistribution"][0]["route"] == "FAQ"
    assert faq_body["byIssueType"][0]["issueTypeId"] == "vpn.connection_failed"

    issue_routes = client.get(
        "/api/issues/vpn.connection_failed/routes?preset=30d",
        headers=backoffice_headers(),
    )
    assert issue_routes.status_code == 200
    assert issue_routes.json()["routes"][0]["attribution"]["faqIds"][0]["id"] == "faq-id-vpn-001"


# =========================================================================
# REQ-027: 全域搜尋與對話/知識關鍵字搜尋
# =========================================================================

@pytest.mark.asyncio
async def test_global_and_module_keyword_search(tmp_path: Path) -> None:
    """REQ-027: Global search and individual module search support keyword search across records."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)

    # 1. Seed conversation event with searchable user query
    events = [
        _event(
            event_id="search-conv-turn-1",
            event_type="turn.received",
            occurred_at=now - timedelta(hours=1),
            conversation_id="conv-secret-project",
            correlation_id="corr-sec-1",
            turn_id="turn-sec-1",
            actor_ref="developer@corp.local",
            payload={"messageMasked": "請問機密專案 ProjectTitan 的權限如何申請？"},
        ),
        _event(
            event_id="search-conv-ans-1",
            event_type="answer.completed",
            occurred_at=now - timedelta(hours=1),
            conversation_id="conv-secret-project",
            correlation_id="corr-sec-1",
            turn_id="turn-sec-1",
            payload={"answerMasked": "請至機密管理平台提交 ProjectTitan 存取申請。"},
        ),
    ]

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    # Test conversation keyword search
    conv_resp = client.get("/api/conversations?query=ProjectTitan", headers=backoffice_headers())
    assert conv_resp.status_code == 200
    assert len(conv_resp.json()["items"]) == 1
    assert conv_resp.json()["items"][0]["conversationId"] == "conv-secret-project"

    # Negative search
    no_resp = client.get("/api/conversations?query=NonExistentTermXYZ", headers=backoffice_headers())
    assert no_resp.status_code == 200
    assert len(no_resp.json()["items"]) == 0

    # Test global search across modules
    search_resp = client.get("/api/governance/search?q=ProjectTitan", headers=backoffice_headers())
    assert search_resp.status_code == 200
    search_hits = search_resp.json()["hits"]
    assert any(h["type"] == "CONVERSATION" and h["id"] == "conv-secret-project" for h in search_hits)
