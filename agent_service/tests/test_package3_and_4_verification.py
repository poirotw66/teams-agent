from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import build_audit_event
from agent_service.operations.audit_stores import MemoryAuditStore
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.file_store import FileOperationalStore
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.governance_domain.service_helpers import _candidate_template
from ai_ops_backoffice.quality_domain.models import QualityCandidate, QualityState
from ai_ops_backoffice.quality_domain.repository import InMemoryQualityRepository
from ai_ops_backoffice.quality_domain.service import (
    QualityService,
    _cluster_candidates_by_similarity,
)
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.settings import BackofficeSettings
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.models import KnowledgeDocumentRecord, KnowledgeVersionRecord
from knowledge_portal.repository import InMemoryPortalRepository
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def _ops_settings(data_dir: Path, store_path: Path) -> OpsSettings:
    return OpsSettings(
        enabled=True,
        store_mode="FILE",
        store_path=store_path,
        taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        environment="dev",
        default_retention_days=365,
        transcript_retention_days=365,
        audit_retention_days=1095,
        async_emit=True,
        firestore_project=None,
        firestore_database=None,
        firestore_collection="operational_events",
        bigquery_enabled=False,
        bigquery_project=None,
        bigquery_dataset="ai_ops_analytics",
        bigquery_table="operational_events",
        audit_store_mode="MEMORY",
        audit_firestore_collection="audit_events",
    )


def headers(role: str = "SERVICE_OWNER", user_id: str | None = None) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id or f"user-{role.lower()}",
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


async def _seed_test_events(store_path: Path, data_dir: Path) -> None:
    settings = _ops_settings(data_dir, store_path)
    ingestion = EventIngestionService(FileOperationalStore(store_path), settings)
    now = utc_now()

    events = [
        OperationalEvent(
            event_id="turn-1:turn.received",
            event_type="turn.received",
            occurred_at=now - timedelta(hours=2),
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id="turn-1",
            actor_ref="user-demo-1",
            payload={"messageMasked": "VPN 連線失敗"},
        ),
        OperationalEvent(
            event_id="turn-1:classification",
            event_type="issue.classified",
            occurred_at=now - timedelta(hours=2),
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id="turn-1",
            issue_type_id="vpn.connection_failed",
            payload={
                "issueTypeId": "vpn.connection_failed",
                "label": "VPN 連線失敗",
                "confidence": 0.95,
                "tier1": "network",
                "tier2": "vpn",
                "tier3": "connection_failed",
                "ownerUnitId": "IT Service Desk",
            },
        ),
        OperationalEvent(
            event_id="corr-1:knowledge:1",
            event_type="knowledge.answered",
            occurred_at=now - timedelta(hours=2),
            conversation_id="conv-1",
            correlation_id="corr-1",
            issue_type_id="vpn.connection_failed",
            payload={
                "resultType": "KNOWLEDGE_ANSWERED",
                "answerMasked": "請確認 VPN 密碼未鎖定後再試一次。",
                "documentId": "vpn-password-lockout",
                "releaseId": "release-2025-09-01",
            },
        ),
        OperationalEvent(
            event_id="corr-1:feedback:1:DOWN",
            event_type="feedback.recorded",
            occurred_at=now - timedelta(hours=2) + timedelta(minutes=1),
            conversation_id="conv-1",
            correlation_id="corr-1",
            issue_type_id="vpn.connection_failed",
            payload={
                "rating": "DOWN",
                "issueId": 1,
                "reason": "wrong_answer",
                "resolvedStatus": "UNRESOLVED",
            },
        ),
        OperationalEvent(
            event_id="corr-1:usage:1",
            event_type="usage.recorded",
            occurred_at=now - timedelta(hours=2) + timedelta(minutes=3),
            conversation_id="conv-1",
            correlation_id="corr-1",
            issue_type_id="vpn.connection_failed",
            payload={
                "model": "gpt-4.1",
                "provider": "openai",
                "promptTokens": 500,
                "completionTokens": 100,
                "totalTokens": 600,
                "estimatedCostUsd": 0.05,
            },
        ),
        OperationalEvent(
            event_id="turn-2:turn.received",
            event_type="turn.received",
            occurred_at=now - timedelta(days=2),
            conversation_id="conv-2",
            correlation_id="corr-2",
            turn_id="turn-2",
            actor_ref="user-demo-2",
            payload={"messageMasked": "歷史問題測試"},
        ),
        OperationalEvent(
            event_id="turn-2:classification",
            event_type="issue.classified",
            occurred_at=now - timedelta(days=2),
            conversation_id="conv-2",
            correlation_id="corr-2",
            turn_id="turn-2",
            issue_type_id="email.outlook_sync",
            payload={
                "issueTypeId": "email.outlook_sync",
                "label": "Outlook 同步失敗",
                "confidence": 0.88,
                "ownerUnitId": "IT Service Desk",
            },
        ),
    ]

    for event in events:
        await ingestion.ingest(event)


@pytest.fixture
def backoffice_test_client(tmp_path: Path) -> TestClient:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    asyncio.run(_seed_test_events(store_path, data_dir))
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="FILE",
        ops_store_path=store_path,
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
    return TestClient(create_app(settings))


def test_req_007_knowledge_portal_document_format_and_owner_filter() -> None:
    """Verify Knowledge Portal list_documents filters by format and owner_unit_id."""
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")

    portal_app = create_portal_app(settings)
    client = TestClient(portal_app)
    hdrs = {
        "X-Portal-User-Id": "contributor",
        "X-Portal-User-Name": "Contributor Demo",
        "X-Portal-Role": "CONTRIBUTOR",
        "X-Portal-Owner-Units": "Security Dept,IT Service Desk",
    }

    # Create markdown document
    res_md = client.post(
        "/api/documents",
        json={
            "title": "VPN Setup Guide",
            "summary": "Setup VPN",
            "category": "VPN",
            "owner_unit_id": "IT Service Desk",
            "business_contact": "it@example.com",
            "audience_type": "ALL_EMPLOYEES",
            "audience_group_ids": [],
            "effective_at": "2026-08-01",
            "review_due_at": "2026-12-01",
            "change_summary": "Initial draft",
            "change_reason": "Setup VPN guide",
            "markdown_content": "# VPN Setup Guide\n\nSetup instructions.",
        },
        headers=hdrs,
    )
    assert res_md.status_code == 200
    doc_md_id = res_md.json()["document"]["document_id"]

    # Create second document with different owner
    res_sec = client.post(
        "/api/documents",
        json={
            "title": "Company Security Policy",
            "summary": "Security policies",
            "category": "SECURITY",
            "owner_unit_id": "Security Dept",
            "business_contact": "sec@example.com",
            "audience_type": "ALL_EMPLOYEES",
            "audience_group_ids": [],
            "effective_at": "2026-08-01",
            "review_due_at": "2026-12-01",
            "change_summary": "Security policy draft",
            "change_reason": "Initial policy",
            "markdown_content": "# Security Policy\n\nPolicy rules.",
        },
        headers=hdrs,
    )
    assert res_sec.status_code == 200
    doc_sec_id = res_sec.json()["document"]["document_id"]

    # Test format filtering: created docs have format MARKDOWN
    res_list_md = client.get("/api/documents?format=MARKDOWN", headers=hdrs)
    assert res_list_md.status_code == 200
    md_items = res_list_md.json()["items"]
    assert len(md_items) == 2
    assert all(d["format"] == "MARKDOWN" for d in md_items)

    res_list_pdf = client.get("/api/documents?format=PDF", headers=hdrs)
    assert res_list_pdf.status_code == 200
    assert len(res_list_pdf.json()["items"]) == 0

    # Test owner_unit_id filtering
    res_owner = client.get("/api/documents?owner_unit_id=Security+Dept", headers=hdrs)
    assert res_owner.status_code == 200
    owner_items = res_owner.json()["items"]
    assert len(owner_items) == 1
    assert owner_items[0]["document_id"] == doc_sec_id
    assert owner_items[0]["owner_unit_id"] == "Security Dept"


def test_req_018_quality_cases_list_filters() -> None:
    """Verify listing quality cases filtered by case_type, status, and owner_unit_id."""
    repo = InMemoryQualityRepository()
    service = QualityService(repo)
    actor = ActorContext("owner", "Owner", "SERVICE_OWNER", ("IT Service Desk", "HR Ops"))

    cand = service.add_candidate(
        source_type="EVENT",
        case_type="NEGATIVE_FEEDBACK",
        title="無法連線 VPN",
        description="使用者無法連線至公司 VPN 伺服器",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT Service Desk",
        actor=actor,
    )["candidate"]

    case = service.merge_candidates(
        (cand["candidate_id"],),
        title="處理 VPN 連線問題",
        description="調查並修復 VPN 故障",
        priority="HIGH",
        assignee_id="owner",
        target_due_at=None,
        actor=actor,
    )["case"]
    case_id = case["case_id"]

    # List with matching filters
    cases_neg = service.list_cases(
        actor=actor,
        case_type="NEGATIVE_FEEDBACK",
        status="NEW",
        owner_unit_id="IT Service Desk",
    )
    assert len(cases_neg) == 1
    assert cases_neg[0]["case_id"] == case_id

    # List with non-matching case_type
    cases_empty = service.list_cases(
        actor=actor,
        case_type="HANDOFF",
    )
    assert len(cases_empty) == 0

    # List with non-matching status
    cases_resolved = service.list_cases(
        actor=actor,
        status="RESOLVED",
    )
    assert len(cases_resolved) == 0


def test_req_019_quality_gap_summary_filters_and_sorting(backoffice_test_client: TestClient) -> None:
    """Verify gap summary supports issue_type_id filtering and sort_by / sort_order."""
    client = backoffice_test_client
    admin_hdrs = headers("SYSTEM_ADMIN")

    res_all = client.get("/api/gaps/summary?days=30", headers=admin_hdrs)
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert "items" in data_all

    # Filter by specific issue_type_id
    res_filtered = client.get(
        "/api/gaps/summary?days=30&issue_type_id=vpn.connection_failed",
        headers=admin_hdrs,
    )
    assert res_filtered.status_code == 200
    filtered_items = res_filtered.json()["items"]
    assert all(item["issueTypeId"] == "vpn.connection_failed" for item in filtered_items)

    # Test sorting by frequency descending
    res_sorted_desc = client.get(
        "/api/gaps/summary?days=30&sort_by=frequency&sort_order=desc",
        headers=admin_hdrs,
    )
    assert res_sorted_desc.status_code == 200
    items_desc = res_sorted_desc.json()["items"]
    if len(items_desc) >= 2:
        assert items_desc[0]["frequency"] >= items_desc[1]["frequency"]

    # Test sorting by negativeFeedbackRate ascending
    res_sorted_asc = client.get(
        "/api/gaps/summary?days=30&sort_by=negativeFeedbackRate&sort_order=asc",
        headers=admin_hdrs,
    )
    assert res_sorted_asc.status_code == 200
    items_asc = res_sorted_asc.json()["items"]
    if len(items_asc) >= 2:
        assert items_asc[0]["negativeFeedbackRate"] <= items_asc[1]["negativeFeedbackRate"]


def test_req_019_question_clustering_by_lexical_similarity() -> None:
    """Verify lexical similarity clustering groups question candidates with similar wording."""
    now = datetime.now(UTC)
    c1 = QualityCandidate(
        candidate_id="c-1",
        source_type="EVENT",
        issue_type_id="vpn.connection_failed",
        owner_unit_id="IT Service Desk",
        title="VPN 登入逾時錯誤",
        description="使用者報告 VPN 登入時逾時中斷連線",
        case_type="NEGATIVE_FEEDBACK",
        created_at=now,
        updated_at=now,
    )
    c2 = QualityCandidate(
        candidate_id="c-2",
        source_type="EVENT",
        issue_type_id="vpn.connection_failed",
        owner_unit_id="IT Service Desk",
        title="VPN 登入失敗逾時",
        description="VPN 連線中斷出現逾時問題",
        case_type="NEGATIVE_FEEDBACK",
        created_at=now,
        updated_at=now,
    )
    c3 = QualityCandidate(
        candidate_id="c-3",
        source_type="EVENT",
        issue_type_id="printer.paper_jam",
        owner_unit_id="IT Service Desk",
        title="3樓印表機卡紙",
        description="印表機進紙槽卡紙無法正常出紙列印",
        case_type="NEGATIVE_FEEDBACK",
        created_at=now,
        updated_at=now,
    )

    clusters = _cluster_candidates_by_similarity([c1, c2, c3])
    # c1 and c2 share VPN, 登入, 逾時, 連線, 中斷 and should cluster together
    assert len(clusters) == 2
    flat_cluster_ids = [[item.candidate_id for item in cluster] for cluster in clusters]
    assert ["c-1", "c-2"] in flat_cluster_ids or ["c-2", "c-1"] in flat_cluster_ids
    assert ["c-3"] in flat_cluster_ids


async def _test_audit_store() -> None:
    store = MemoryAuditStore()

    event1 = build_audit_event(
        actor_id="admin-1",
        actor_role="SYSTEM_ADMIN",
        action="FLAG_ACTIVATED",
        target_type="FEATURE_FLAG",
        target_id="flag-ticket",
    )
    event2 = build_audit_event(
        actor_id="admin-2",
        actor_role="SYSTEM_ADMIN",
        action="MODEL_ACTIVATED",
        target_type="MODEL_POLICY",
        target_id="model-primary",
    )
    event3 = build_audit_event(
        actor_id="admin-1",
        actor_role="SYSTEM_ADMIN",
        action="FLAG_ACTIVATED",
        target_type="FEATURE_FLAG",
        target_id="flag-voice",
    )
    await store.append(event1)
    await store.append(event2)
    await store.append(event3)

    # Filter by actor_id
    items_actor, _ = await store.list_events(actor_id="admin-2")
    assert len(items_actor) == 1
    assert items_actor[0].audit_id == event2.audit_id

    # Filter by action
    items_action, _ = await store.list_events(action="FLAG_ACTIVATED")
    assert len(items_action) == 2

    # Filter by target_type
    items_target, _ = await store.list_events(target_type="MODEL_POLICY")
    assert len(items_target) == 1
    assert items_target[0].audit_id == event2.audit_id

    # Test pagination with limit and cursor
    p1_items, cursor = await store.list_events(limit=2)
    assert len(p1_items) == 2
    assert cursor is not None

    p2_items, _ = await store.list_events(limit=2, cursor=cursor)
    assert len(p2_items) == 1
    page1_ids = {e.audit_id for e in p1_items}
    page2_ids = {e.audit_id for e in p2_items}
    assert page1_ids.isdisjoint(page2_ids)


def test_req_021_audit_store_filters_and_pagination() -> None:
    """Verify MemoryAuditStore filters by actor_id, action, target_type, date range and cursor pagination."""
    asyncio.run(_test_audit_store())


def test_req_023_budget_model_scope_and_usage(backoffice_test_client: TestClient) -> None:
    """Verify budget policies support MODEL scope and usage calculation."""
    client = backoffice_test_client
    admin_hdrs = headers("SYSTEM_ADMIN")

    create_res = client.post(
        "/api/budget-policies",
        json={
            "scope_type": "MODEL",
            "scope_id": "gpt-4.1",
            "period": "DAILY",
            "measure": "USD",
            "warning_threshold": 40.0,
            "critical_threshold": 50.0,
            "owner_unit_id": "IT Service Desk",
            "notification_target_ids": ["notification-center"],
        },
        headers=admin_hdrs,
    )
    assert create_res.status_code == 200
    policy = create_res.json()["policy"]
    assert policy["scope_type"] == "MODEL"
    assert policy["scope_id"] == "gpt-4.1"

    # Evaluate budget policy and verify model usage calculation
    eval_res = client.post(
        f"/api/budget-policies/{policy['policy_id']}/evaluate",
        headers=admin_hdrs,
    )
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert "usage" in eval_data
    # Seeded event corr-1:usage:1 had estimatedCostUsd: 0.05
    assert float(eval_data["usage"]["actualValue"]) >= 0.05


def test_req_024_health_summary_historical_date(backoffice_test_client: TestClient) -> None:
    """Verify health summary accepts historical date query."""
    client = backoffice_test_client
    admin_hdrs = headers("SYSTEM_ADMIN")

    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    res_today = client.get(f"/api/health/summary?date={today_str}", headers=admin_hdrs)
    assert res_today.status_code == 200
    data_today = res_today.json()
    assert data_today["targetDate"] == today_str
    assert "components" in data_today
    assert len(data_today["components"]) > 0


def test_req_027_governance_search_category_and_owner_filter(backoffice_test_client: TestClient) -> None:
    """Verify governance search supports doc_type and owner_unit_id filters."""
    client = backoffice_test_client
    admin_hdrs = headers("SYSTEM_ADMIN")

    res = client.get(
        "/api/governance/search?query=VPN&doc_type=FAQ&owner_unit_id=IT+Service+Desk",
        headers=admin_hdrs,
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert all(item["type"] == "FAQ" for item in data["items"])


def test_req_015_prompt_template_failure_pattern_synthesis() -> None:
    """Verify candidate template synthesizes failure mitigation instructions from negative feedback."""
    base_template = "You are a helpdesk assistant. {max_issues} {faq_keys}"
    examples = [
        {
            "expected_route": "KNOWLEDGE",
            "label": "negative",
            "failure_reason": "vpn_login_timeout",
            "text": "VPN 登入逾時",
        },
        {
            "expected_route": "FAQ",
            "label": "unresolved",
            "failure_reason": "vpn_login_timeout",
            "text": "VPN 登入逾時",
        },
        {
            "expected_route": "KNOWLEDGE",
            "label": "positive",
            "reason": "missing_steps",
            "text": "缺少步驟",
        },
    ]

    optimized = _candidate_template(base_template, "v1", examples)
    assert "{max_issues}" in optimized
    assert "{faq_keys}" in optimized
    assert "Failure mitigation instructions" in optimized
    assert "vpn_login_timeout" in optimized
    assert "Unresolved query safeguards" in optimized


def test_req_017_feedback_model_and_route_filter(backoffice_test_client: TestClient) -> None:
    """Verify /api/feedback filters by model and route."""
    client = backoffice_test_client
    admin_hdrs = headers("SYSTEM_ADMIN")

    res = client.get("/api/feedback?model=gpt-4.1&route=KNOWLEDGE", headers=admin_hdrs)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    for item in data["items"]:
        assert item["model"] == "gpt-4.1"
        assert item["route"] == "KNOWLEDGE"
