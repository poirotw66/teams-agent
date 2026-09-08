from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent
from ai_ops_backoffice.api import create_app as create_backoffice_app
from ai_ops_backoffice.services.export_format import flatten_for_csv, flatten_for_xlsx
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
        "export_content_path": tmp_path / "exports",
        **overrides,
    }
    return BackofficeSettings(**params)


def backoffice_headers(role: str = "KNOWLEDGE_ADMIN", user_id: str = "owner-1") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id,
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def _event(**kwargs) -> OperationalEvent:
    defaults = {
        "environment": "dev",
        "tenant_id": "local-development",
    }
    defaults.update(kwargs)
    return OperationalEvent(**defaults)


# =========================================================================
# REQ-003: 使用者對話紀錄查詢與完整對話匯出
# =========================================================================

@pytest.mark.asyncio
async def test_user_conversation_history_query_and_6_months_range(tmp_path: Path) -> None:
    """REQ-003: Query by user_id, 186 days range (6 months), and verify rich turn details."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)
    five_months_ago = now - timedelta(days=150)

    # Seed conversation events with turns, AI answer, issue, model, feedback, handoff
    events = [
        # Turn 1
        _event(
            event_id="t1:turn.received",
            event_type="turn.received",
            occurred_at=five_months_ago,
            conversation_id="conv-user-1",
            correlation_id="corr-t1",
            turn_id="turn-t1",
            actor_ref="user.alice@corp.local",
            payload={"messageMasked": "請問如何申請遠端辦公 VPN？", "userId": "user.alice@corp.local"},
        ),
        _event(
            event_id="t1:issue.extracted",
            event_type="issue.extracted",
            occurred_at=five_months_ago,
            conversation_id="conv-user-1",
            correlation_id="corr-t1",
            turn_id="turn-t1",
            issue_type_id="vpn.connection_failed",
            payload={"descriptionMasked": "申請遠端辦公 VPN"},
        ),
        _event(
            event_id="t1:usage.recorded",
            event_type="usage.recorded",
            occurred_at=five_months_ago,
            conversation_id="conv-user-1",
            correlation_id="corr-t1",
            turn_id="turn-t1",
            payload={"model": "gemini-2.5-flash"},
        ),
        _event(
            event_id="t1:knowledge.answered",
            event_type="knowledge.answered",
            occurred_at=five_months_ago,
            conversation_id="conv-user-1",
            correlation_id="corr-t1",
            turn_id="turn-t1",
            payload={
                "resultType": "KNOWLEDGE_ANSWERED",
                "answerMasked": "請至 IT Portal 填寫 VPN 申請單。",
                "documentId": "vpn-guide-doc",
                "sourcePath": "docs/vpn/quickstart.md",
                "releaseId": "release-v1",
            },
        ),
        _event(
            event_id="t1:feedback.recorded",
            event_type="feedback.recorded",
            occurred_at=five_months_ago + timedelta(seconds=20),
            conversation_id="conv-user-1",
            correlation_id="corr-t1",
            turn_id="turn-t1",
            payload={"rating": "UP", "reason": "說明清楚", "resolvedStatus": "RESOLVED"},
        ),
        # Turn 2 with handoff and ticket creation
        _event(
            event_id="t2:turn.received",
            event_type="turn.received",
            occurred_at=five_months_ago + timedelta(minutes=5),
            conversation_id="conv-user-1",
            correlation_id="corr-t2",
            turn_id="turn-t2",
            actor_ref="user.alice@corp.local",
            issue_type_id="vpn.connection_failed",
            payload={"messageMasked": "我的申請單一直卡在主管簽核中", "userId": "user.alice@corp.local"},
        ),
        _event(
            event_id="t2:issue.extracted",
            event_type="issue.extracted",
            occurred_at=five_months_ago + timedelta(minutes=5),
            conversation_id="conv-user-1",
            correlation_id="corr-t2",
            turn_id="turn-t2",
            issue_type_id="vpn.connection_failed",
            payload={"descriptionMasked": "申請單卡在主管簽核中"},
        ),
        _event(
            event_id="t2:route.selected",
            event_type="route.selected",
            occurred_at=five_months_ago + timedelta(minutes=5),
            conversation_id="conv-user-1",
            correlation_id="corr-t2",
            turn_id="turn-t2",
            issue_type_id="vpn.connection_failed",
            payload={"route": "HANDOFF"},
        ),
        _event(
            event_id="t2:handoff.offered",
            event_type="handoff.offered",
            occurred_at=five_months_ago + timedelta(minutes=6),
            conversation_id="conv-user-1",
            correlation_id="corr-t2",
            turn_id="turn-t2",
            issue_type_id="vpn.connection_failed",
            payload={"status": "OFFERED"},
        ),
        _event(
            event_id="t2:ticket.created",
            event_type="ticket.created",
            occurred_at=five_months_ago + timedelta(minutes=7),
            conversation_id="conv-user-1",
            correlation_id="corr-t2",
            turn_id="turn-t2",
            issue_type_id="vpn.connection_failed",
            payload={"ticketId": "TCK-VPN-9001", "backend": "JIRA"},
        ),
    ]

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    # 1. Query by user_id over 186 days (6 months)
    resp = client.get(
        "/api/conversations?days=186&user_id=user.alice@corp.local",
        headers=backoffice_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    conv = data["items"][0]
    assert conv["conversationId"] == "conv-user-1"
    assert conv["turnCount"] == 2
    assert conv["ticketIds"] == ["TCK-VPN-9001"]
    assert conv["ticketCount"] == 1
    assert conv["ticketStatus"] == "CREATED"
    assert conv["handoffStatus"] == "OFFERED"
    assert "turns" in conv
    assert len(conv["turns"]) == 2

    turn1 = conv["turns"][0]
    assert turn1["turnId"] == "turn-t1"
    assert "VPN" in turn1["userMessage"]
    assert "IT Portal" in turn1["aiReply"]
    assert turn1["model"] == "gemini-2.5-flash"
    assert turn1["issueTypeId"] == "vpn.connection_failed"
    assert "vpn-guide-doc" in turn1["documentIds"]
    assert "docs/vpn/quickstart.md" in turn1["sourcePaths"]
    assert turn1["feedbackRating"] == "UP"
    assert turn1["feedbackReason"] == "說明清楚"
    assert turn1["resolvedStatus"] == "RESOLVED"

    turn2 = conv["turns"][1]
    assert turn2["turnId"] == "turn-t2"
    assert turn2["route"] == "HANDOFF"
    assert turn2["handoffStatus"] == "OFFERED"
    assert turn2["ticketId"] == "TCK-VPN-9001"
    assert turn2["ticketStatus"] == "CREATED"
    assert turn2["ticketBackend"] == "JIRA"

    # 2. Query by conversation_id directly
    direct_resp = client.get(
        "/api/conversations?conversation_id=conv-user-1",
        headers=backoffice_headers(),
    )
    assert direct_resp.status_code == 200
    assert len(direct_resp.json()["items"]) == 1

    # 3. Query by source filter
    source_hit_resp = client.get(
        "/api/conversations?days=186&source=quickstart.md",
        headers=backoffice_headers(),
    )
    assert source_hit_resp.status_code == 200
    assert len(source_hit_resp.json()["items"]) == 1

    source_miss_resp = client.get(
        "/api/conversations?days=186&source=nonexistent.pdf",
        headers=backoffice_headers(),
    )
    assert source_miss_resp.status_code == 200
    assert len(source_miss_resp.json()["items"]) == 0

    # 4. Query by message / query filter (matches ticketId or question)
    query_hit_resp = client.get(
        "/api/conversations?days=186&query=9001",
        headers=backoffice_headers(),
    )
    assert query_hit_resp.status_code == 200
    assert len(query_hit_resp.json()["items"]) == 1

    # 5. Verify query audit logging captures filter details and resultCount
    audit_events, _ = await query_svc.audit_store.list_events(limit=100)
    query_audits = [
        event
        for event in audit_events
        if event.action == "query.conversations"
    ]
    assert len(query_audits) >= 1
    # Check latest audit record has filter details in `after`
    latest_audit = query_audits[-1]
    assert latest_audit.target_id == "conversations"
    assert latest_audit.after is not None
    assert "resultCount" in latest_audit.after


def test_conversations_export_csv_and_xlsx_full_dialogue(tmp_path: Path) -> None:
    """REQ-003: Verify CSV and XLSX export outputs complete dialog rows with question, reply, model, feedback."""
    payload = {
        "exportMetadata": {
            "exportType": "conversations",
            "exportFormat": "csv",
            "recordCount": 1,
        },
        "data": {
            "items": [
                {
                    "conversationId": "conv-export-100",
                    "actorRef": "emp.001@company.com",
                    "channelScope": "teams_private",
                    "routes": ["KNOWLEDGE"],
                    "turns": [
                        {
                            "turnId": "turn-101",
                            "occurredAt": "2026-03-01T08:30:00Z",
                            "actorRef": "emp.001@company.com",
                            "userMessage": "Outlook 信箱爆滿無法收信",
                            "aiReply": "建議至 Webmail 清理垃圾郵件或封存舊郵件。",
                            "model": "gemini-2.5-pro",
                            "issueTypeId": "mail.mailbox_full",
                            "route": "KNOWLEDGE",
                            "faqKey": None,
                            "documentIds": ["mail-quota-faq"],
                            "sourcePaths": ["kb/mail/quota.pdf"],
                            "feedbackRating": "UP",
                            "feedbackReason": "解決了收信問題",
                            "resolvedStatus": "RESOLVED",
                            "handoffStatus": None,
                            "ticketId": "TCK-MAIL-404",
                            "ticketStatus": "CREATED",
                            "ticketBackend": "SERVICE_NOW",
                        }
                    ],
                }
            ]
        },
    }

    # CSV output verification
    csv_str = flatten_for_csv(payload)
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]
    assert row["conversationId"] == "conv-export-100"
    assert row["turnId"] == "turn-101"
    assert row["userMessage"] == "Outlook 信箱爆滿無法收信"
    assert "清理垃圾郵件" in row["aiReply"]
    assert row["model"] == "gemini-2.5-pro"
    assert row["issueTypeId"] == "mail.mailbox_full"
    assert row["documentIds"] == "mail-quota-faq"
    assert row["sourcePaths"] == "kb/mail/quota.pdf"
    assert row["feedbackRating"] == "UP"
    assert row["feedbackReason"] == "解決了收信問題"
    assert row["resolvedStatus"] == "RESOLVED"
    assert row["ticketId"] == "TCK-MAIL-404"
    assert row["ticketStatus"] == "CREATED"
    assert row["ticketBackend"] == "SERVICE_NOW"

    # XLSX output verification
    xlsx_bytes = flatten_for_xlsx(payload)
    assert xlsx_bytes.startswith(b"PK")


@pytest.mark.asyncio
async def test_export_conversations_api_with_operator_reason_and_filters(tmp_path: Path) -> None:
    """REQ-003: Verify operator reason is persisted in export job and filter parameters are forwarded."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)

    events = [
        _event(
            event_id="e1:turn.received",
            event_type="turn.received",
            occurred_at=now - timedelta(days=10),
            conversation_id="conv-exp-test",
            correlation_id="corr-exp-1",
            turn_id="turn-exp-1",
            actor_ref="user.bob@corp.local",
            issue_type_id="hardware.laptop_issue",
            payload={"messageMasked": "需要申請新筆電", "userId": "user.bob@corp.local"},
        ),
        _event(
            event_id="e1:issue.extracted",
            event_type="issue.extracted",
            occurred_at=now - timedelta(days=10),
            conversation_id="conv-exp-test",
            correlation_id="corr-exp-1",
            turn_id="turn-exp-1",
            issue_type_id="hardware.laptop_issue",
            payload={"descriptionMasked": "需要申請新筆電"},
        ),
        _event(
            event_id="e1:knowledge.answered",
            event_type="knowledge.answered",
            occurred_at=now - timedelta(days=10),
            conversation_id="conv-exp-test",
            correlation_id="corr-exp-1",
            turn_id="turn-exp-1",
            issue_type_id="hardware.laptop_issue",
            payload={
                "resultType": "KNOWLEDGE_ANSWERED",
                "answerMasked": "請至設備入口網站申請。",
                "documentId": "laptop-policy-doc",
                "sourcePath": "docs/hardware/laptop.md",
            },
        ),
        _event(
            event_id="e1:ticket.created",
            event_type="ticket.created",
            occurred_at=now - timedelta(days=10),
            conversation_id="conv-exp-test",
            correlation_id="corr-exp-1",
            turn_id="turn-exp-1",
            issue_type_id="hardware.laptop_issue",
            payload={"ticketId": "TCK-LAPTOP-101", "backend": "SERVICE_NOW"},
        ),
    ]

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    # Trigger export with operator reason, source filter, and query filter
    export_payload = {
        "export_type": "conversations",
        "reason": "Q3 2026 BU IT Audit - Hardware Requests",
        "days": 30,
        "export_format": "csv",
        "source": "laptop",
        "query": "筆電",
    }
    resp = client.post(
        "/api/exports",
        json=export_payload,
        headers=backoffice_headers(),
    )
    assert resp.status_code == 200
    job_info = resp.json()
    job_id = job_info["jobId"]

    # Verify export status and retrieve job detail
    job_resp = client.get(f"/api/exports/{job_id}", headers=backoffice_headers())
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    assert job_data["reason"] == "Q3 2026 BU IT Audit - Hardware Requests"
    assert job_data["exportType"] == "conversations"

    # Download export content and verify rows contain ticket and source details
    download_resp = client.get(f"/api/exports/{job_id}/download", headers=backoffice_headers())
    assert download_resp.status_code == 200
    csv_text = download_resp.text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["conversationId"] == "conv-exp-test"
    assert rows[0]["ticketId"] == "TCK-LAPTOP-101"
    assert rows[0]["ticketStatus"] == "CREATED"
    assert "laptop.md" in rows[0]["sourcePaths"]


def test_conversation_retention_ttl_alignment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """REQ-003: Verify runtime conversation and handoff retention policies align to 365 days (1 year max)."""
    monkeypatch.delenv("CONVERSATION_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("HANDOFF_RETENTION_DAYS", raising=False)
    from agent_service.settings import RagSettings

    # Default retention is 365 days
    settings = RagSettings.from_env()
    assert settings.conversation_retention_days == 365
    assert settings.handoff_retention_days == 365

    # Values exceeding 365 days violate the 1-year policy bound and raise ValueError
    with pytest.raises(ValueError, match="CONVERSATION_RETENTION_DAYS must be between 1 and 365"):
        RagSettings(data_dir=tmp_path, index_path=tmp_path / "idx", conversation_retention_days=366).validate()

    with pytest.raises(ValueError, match="HANDOFF_RETENTION_DAYS must be between 1 and 365"):
        RagSettings(data_dir=tmp_path, index_path=tmp_path / "idx", handoff_retention_days=366).validate()



# =========================================================================
# REQ-008: 文件命中與回饋精確歸因
# =========================================================================

@pytest.mark.asyncio
async def test_document_feedback_exact_attribution_no_cross_turn_contamination(tmp_path: Path) -> None:
    """REQ-008: Negative feedback on Turn 2 citing Doc B must not be attributed to Doc A in Turn 1."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)

    # Conversation with 2 turns:
    # Turn 1 hits doc-A (no feedback)
    # Turn 2 hits doc-B and receives DOWN feedback
    events = [
        # Turn 1: hits doc-A
        _event(
            event_id="turn-1:turn.received",
            event_type="turn.received",
            occurred_at=now - timedelta(minutes=10),
            conversation_id="conv-multi-turn",
            correlation_id="corr-turn-1",
            turn_id="turn-1",
            issue_type_id="vpn.connection_failed",
            payload={"messageMasked": "Doc A query"},
        ),
        _event(
            event_id="turn-1:knowledge.answered",
            event_type="knowledge.answered",
            occurred_at=now - timedelta(minutes=10),
            conversation_id="conv-multi-turn",
            correlation_id="corr-turn-1",
            turn_id="turn-1",
            issue_type_id="vpn.connection_failed",
            payload={
                "resultType": "KNOWLEDGE_ANSWERED",
                "documentId": "doc-A",
                "releaseId": "release-v1",
            },
        ),
        # Turn 2: hits doc-B
        _event(
            event_id="turn-2:turn.received",
            event_type="turn.received",
            occurred_at=now - timedelta(minutes=5),
            conversation_id="conv-multi-turn",
            correlation_id="corr-turn-2",
            turn_id="turn-2",
            issue_type_id="vpn.connection_failed",
            payload={"messageMasked": "Doc B query"},
        ),
        _event(
            event_id="turn-2:knowledge.answered",
            event_type="knowledge.answered",
            occurred_at=now - timedelta(minutes=5),
            conversation_id="conv-multi-turn",
            correlation_id="corr-turn-2",
            turn_id="turn-2",
            issue_type_id="vpn.connection_failed",
            payload={
                "resultType": "KNOWLEDGE_ANSWERED",
                "documentId": "doc-B",
                "releaseId": "release-v1",
            },
        ),
        # Feedback on Turn 2: DOWN
        _event(
            event_id="turn-2:feedback.recorded",
            event_type="feedback.recorded",
            occurred_at=now - timedelta(minutes=4),
            conversation_id="conv-multi-turn",
            correlation_id="corr-turn-2",
            turn_id="turn-2",
            issue_type_id="vpn.connection_failed",
            payload={"rating": "DOWN", "reason": "Doc B instructions inaccurate"},
        ),
    ]

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    actor = ActorContext(
        user_id="analyst-1",
        display_name="Analyst",
        role="KNOWLEDGE_ADMIN",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="local-development",
    )

    # Check Doc A: MUST HAVE 0 negative feedback
    perf_a = await query_svc.document_performance(actor, "doc-A", days=30)
    assert perf_a["hitCount"] == 1
    assert perf_a["negativeFeedbackCount"] == 0
    assert perf_a["positiveFeedbackCount"] == 0

    # Check Doc B: MUST HAVE 1 negative feedback
    perf_b = await query_svc.document_performance(actor, "doc-B", days=30)
    assert perf_b["hitCount"] == 1
    assert perf_b["negativeFeedbackCount"] == 1


# =========================================================================
# REQ-009: 文件命中 Issue 分析與六個月明細分頁
# =========================================================================

@pytest.mark.asyncio
async def test_document_hit_issue_analysis_and_pagination(tmp_path: Path) -> None:
    """REQ-009: 6-month document hit issue distribution, filtering by issue, and cursor pagination."""
    settings = _backoffice_settings(tmp_path)
    now = datetime.now(UTC)

    # Seed 5 hits over the last 150 days (6 months range)
    events = []
    for i in range(5):
        occurred = now - timedelta(days=20 * (i + 1))
        issue_id = "vpn.connection_failed" if i % 2 == 0 else "network.internet_slow"
        events.append(
            _event(
                event_id=f"hit-{i}:knowledge.answered",
                event_type="knowledge.answered",
                occurred_at=occurred,
                conversation_id=f"conv-hit-{i}",
                correlation_id=f"corr-hit-{i}",
                turn_id=f"turn-hit-{i}",
                issue_type_id=issue_id,
                payload={
                    "resultType": "KNOWLEDGE_ANSWERED",
                    "documentId": "target-doc-99",
                    "releaseId": "release-v2",
                    "chunkId": f"chunk-{i}",
                },
            )
        )

    query_svc = BackofficeQueryService(settings)
    for ev in events:
        await query_svc._runtime.store.append(ev)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    # 1. Query document performance with 186 days (6 months)
    resp = client.get(
        "/api/knowledge/target-doc-99/performance?days=186&limit=2",
        headers=backoffice_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["hitCount"] == 5
    assert data["totalHits"] == 5
    assert len(data["hits"]) == 2
    assert data["hasMore"] is True
    assert data["nextCursor"] == "2"

    # Verify Issue Type Distribution covers both types
    issue_dist = {item["issueTypeId"]: item["count"] for item in data["issueTypeDistribution"]}
    assert issue_dist["vpn.connection_failed"] == 3
    assert issue_dist["network.internet_slow"] == 2

    # 2. Fetch second page with cursor
    resp_page2 = client.get(
        f"/api/knowledge/target-doc-99/performance?days=186&limit=2&cursor={data['nextCursor']}",
        headers=backoffice_headers(),
    )
    assert resp_page2.status_code == 200
    page2_data = resp_page2.json()
    assert len(page2_data["hits"]) == 2
    assert page2_data["cursor"] == "2"
    assert page2_data["nextCursor"] == "4"

    # 3. Filter by issue_type_id
    filter_resp = client.get(
        "/api/knowledge/target-doc-99/performance?days=186&issue_type_id=network.internet_slow",
        headers=backoffice_headers(),
    )
    assert filter_resp.status_code == 200
    filtered_data = filter_resp.json()
    assert filtered_data["totalHits"] == 2
    assert all(hit["issueTypeId"] == "network.internet_slow" for hit in filtered_data["hits"])
