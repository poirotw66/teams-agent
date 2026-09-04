from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.file_store import FileOperationalStore
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.settings import BackofficeSettings


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


async def _seed_sample_events(store_path: Path, data_dir: Path) -> None:
    settings = _ops_settings(data_dir, store_path)
    ingestion = EventIngestionService(FileOperationalStore(store_path), settings)
    now = utc_now()
    turn_id = "turn-1"
    occurrence_id = f"{turn_id}:issue:1"
    events = [
        OperationalEvent(
            event_id="turn-1:turn.received",
            event_type="turn.received",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            actor_ref="user-demo-vpn-001",
            payload={"messageMasked": "VPN 連線失敗"},
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:issue.extracted",
            event_type="issue.extracted",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={
                "issueId": 1,
                "descriptionMasked": "VPN 連線失敗",
                "route": "KNOWLEDGE",
            },
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:issue.classified",
            event_type="issue.classified",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_occurrence_id=occurrence_id,
            issue_type_id="vpn.connection_failed",
            payload={"classificationSource": "KEYWORD_RULE"},
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:route.selected",
            event_type="route.selected",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_type_id="vpn.connection_failed",
            payload={"route": "KNOWLEDGE"},
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:knowledge.retrieved:1",
            event_type="knowledge.retrieved",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
            issue_type_id="vpn.connection_failed",
            payload={
                "documentId": "vpn-password-lockout",
                "chunkId": "chunk-1",
                "releaseId": "release-2025-09-01",
            },
        ),
        OperationalEvent(
            event_id=f"{occurrence_id}:knowledge.answered",
            event_type="knowledge.answered",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id=turn_id,
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
            occurred_at=now + timedelta(minutes=1),
            conversation_id="conv-1",
            correlation_id="corr-1",
            payload={
                "rating": "DOWN",
                "issueId": 1,
                "reason": "wrong_answer",
                "resolvedStatus": "UNRESOLVED",
            },
        ),
        OperationalEvent(
            event_id="corr-1:feedback:1:UP",
            event_type="feedback.recorded",
            occurred_at=now + timedelta(seconds=30),
            conversation_id="conv-1",
            correlation_id="corr-1",
            payload={
                "rating": "UP",
                "issueId": 1,
                "reason": "helpful",
                "resolvedStatus": "RESOLVED",
            },
        ),
        OperationalEvent(
            event_id="case-1:handoff.offered",
            event_type="handoff.offered",
            occurred_at=now + timedelta(minutes=2),
            conversation_id="conv-1",
            correlation_id="corr-1",
            payload={"status": "OFFERED"},
        ),
        OperationalEvent(
            event_id="corr-1:usage:1",
            event_type="usage.recorded",
            occurred_at=now + timedelta(minutes=3),
            conversation_id="conv-1",
            correlation_id="corr-1",
            issue_type_id="vpn.connection_failed",
            payload={
                "model": "gpt-4.1",
                "provider": "openai",
                "inputTokens": 120,
                "outputTokens": 45,
                "estimatedCostUsd": 0.0025,
                "pricingVersion": "v1",
                "llmCallCount": 1,
            },
        ),
    ]
    await ingestion.ingest_many(events)


@pytest.fixture
def backoffice_client(tmp_path: Path) -> TestClient:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
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
    )
    return TestClient(create_app(settings))


@pytest.fixture
def seeded_backoffice_client(tmp_path: Path) -> TestClient:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    asyncio.run(_seed_sample_events(store_path, data_dir))
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
    )
    return TestClient(create_app(settings))


def headers(role: str = "SERVICE_OWNER") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": "owner.demo",
        "X-Backoffice-User-Name": "Owner Demo",
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
    }


def test_budget_policy_evaluates_scoped_usage_and_manages_alert(
    seeded_backoffice_client: TestClient,
) -> None:
    created = seeded_backoffice_client.post(
        "/api/budget-policies",
        headers=headers(),
        json={
            "scope_type": "PERSONAL",
            "scope_id": "user-demo-vpn-001",
            "period": "DAILY",
            "measure": "TWD",
            "warning_threshold": 0.01,
            "critical_threshold": 0.05,
            "owner_unit_id": "IT Service Desk",
            "notification_target_ids": ["notification-center"],
        },
    )
    assert created.status_code == 200
    policy = created.json()["policy"]

    evaluated = seeded_backoffice_client.post(
        f"/api/budget-policies/{policy['policy_id']}/evaluate",
        headers=headers(),
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["usage"]["actualValue"] == 0.079
    alert = evaluated.json()["alert"]
    assert alert["severity"] == "CRITICAL"
    assert alert["pricing_version"] == "v1"

    alerts = seeded_backoffice_client.get("/api/alerts", headers=headers()).json()["items"]
    assert alerts[0]["deliveries"][0]["status"] == "SENT"
    acknowledged = seeded_backoffice_client.post(
        f"/api/alerts/{alert['alert_id']}/acknowledge",
        headers=headers(),
        json={"expected_etag": alert["etag"], "reason": "owner reviewing usage"},
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["alert"]["status"] == "ACKNOWLEDGED"


def test_prompt_poc_generates_candidate_without_activation(
    backoffice_client: TestClient,
) -> None:
    system_headers = headers("SYSTEM_ADMIN")
    created_example = backoffice_client.post(
        "/api/examples/manual",
        headers=system_headers,
        json={
            "text": "VPN 無法連線",
            "expected_issue_type_id": "vpn.connection_failed",
            "expected_route": "KNOWLEDGE",
            "label": "POSITIVE",
        },
    ).json()["example"]
    verified = backoffice_client.post(
        f"/api/examples/{created_example['example_id']}/review",
        headers=system_headers,
        json={"expected_etag": 1, "approve": True, "reason": "verified for prompt POC"},
    ).json()["example"]
    ai_headers = headers("AI_ADMIN")
    active_response = backoffice_client.get("/api/prompts/active", headers=ai_headers)
    assert active_response.status_code == 200
    active = active_response.json()["prompt"]
    assert active["status"] == "ACTIVE"
    assert "content" in active
    taxonomy_version = backoffice_client.get("/api/taxonomy", headers=ai_headers).json()[
        "taxonomyVersion"
    ]
    now = utc_now()
    generated = backoffice_client.post(
        "/api/prompts/candidates",
        headers={**ai_headers, "X-Correlation-Id": "prompt-poc-1"},
        json={
            "active_prompt_version": active["version"],
            "dataset_version": verified["dataset_version"],
            "taxonomy_version": taxonomy_version,
            "data_range_start": (now - timedelta(days=1)).isoformat(),
            "data_range_end": (now + timedelta(days=1)).isoformat(),
            "masking_policy_version": "mask-v1",
        },
    )
    assert generated.status_code == 200
    candidate = generated.json()["candidate"]
    assert candidate["status"] == "CANDIDATE"
    comparison = backoffice_client.get(
        f"/api/prompts/candidates/{candidate['candidate_id']}/compare",
        headers=ai_headers,
    )
    assert comparison.json()["activeUnchanged"] is True
    assert backoffice_client.post(
        f"/api/prompts/candidates/{candidate['candidate_id']}/activate",
        headers=system_headers,
    ).status_code == 404
    assert backoffice_client.get(
        "/api/prompts/active", headers=headers("ANALYST")
    ).status_code == 403


def test_quality_case_faq_publication_enters_observation(
    seeded_backoffice_client: TestClient,
) -> None:
    writer_headers = headers("KNOWLEDGE_ADMIN")
    refreshed = seeded_backoffice_client.post(
        "/api/quality-candidates/refresh", headers=writer_headers, json={"days": 30}
    ).json()
    candidate = next(item for item in refreshed["items"] if item["issue_type_id"])
    quality_case = seeded_backoffice_client.post(
        "/api/quality-candidates/merge",
        headers=writer_headers,
        json={
            "candidate_ids": [candidate["candidate_id"]], "title": "Improve VPN FAQ",
            "description": "Publish governed answer", "priority": "HIGH",
        },
    ).json()["case"]
    for status in ("TRIAGED", "IN_PROGRESS"):
        quality_case = seeded_backoffice_client.post(
            f"/api/quality-cases/{quality_case['case_id']}/transition",
            headers=writer_headers,
            json={
                "expected_etag": quality_case["etag"], "status": status,
                "reason": "start improvement", "resolution_type": None,
            },
        ).json()["case"]
    drafted = seeded_backoffice_client.post(
        f"/api/quality-cases/{quality_case['case_id']}/faq-draft",
        headers=writer_headers,
        json={
            "expected_case_etag": quality_case["etag"], "faq_key": "VPN_CASE_OBSERVE",
            "question": "VPN 無法連線怎麼辦？", "answer": "請重新連線 VPN。",
            "category": "VPN", "keywords": ["vpn", "連線"],
            "business_contact": "IT Service Desk", "audience_type": "ALL",
        },
    ).json()
    faq_id = drafted["faq"]["faq_id"]
    version_id = drafted["version"]["version_id"]
    for etag, kind, utterance in (
        (1, "POSITIVE", "VPN 無法連線"),
        (2, "NEGATIVE", "我要重設薪資系統密碼"),
    ):
        response = seeded_backoffice_client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/tests",
            headers=writer_headers,
            json={"expected_etag": etag, "kind": kind, "utterance": utterance},
        )
        assert response.status_code == 200
    assert seeded_backoffice_client.post(
        f"/api/faqs/{faq_id}/versions/{version_id}/submit",
        headers=writer_headers, json={"expected_etag": 3},
    ).status_code == 200
    admin_headers = {**headers("SYSTEM_ADMIN"), "X-Backoffice-User-Id": "justin"}
    assert seeded_backoffice_client.post(
        f"/api/faqs/{faq_id}/versions/{version_id}/review",
        headers=admin_headers,
        json={"expected_etag": 4, "approve": True, "reason": "content verified"},
    ).status_code == 200
    activated = seeded_backoffice_client.post(
        f"/api/faqs/{faq_id}/versions/{version_id}/activate",
        headers=admin_headers,
        json={"expected_etag": 5, "reason": "publish improvement"},
    )
    assert activated.status_code == 200
    assert activated.json()["observingCases"][0]["status"] == "OBSERVING"
    observed = seeded_backoffice_client.get(
        f"/api/quality-cases/{quality_case['case_id']}", headers=writer_headers
    ).json()["case"]
    assert observed["faq_ids"] == [faq_id]
    assert observed["observation_baseline"] is not None


def test_phase2_faq_api_lifecycle_persists_and_enforces_governance(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
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
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        faq_store_mode="FILE",
        faq_store_path=tmp_path / "phase2" / "faqs.json",
    )
    writer_headers = {
        **headers("KNOWLEDGE_ADMIN"),
        "X-Backoffice-User-Id": "faq.writer",
        "X-Backoffice-User-Name": "FAQ Writer",
    }
    admin_headers = {
        **headers("SYSTEM_ADMIN"),
        "X-Backoffice-User-Id": "faq.admin",
        "X-Backoffice-User-Name": "FAQ Admin",
    }
    payload = {
        "faq_key": "VPN_CONNECTION_FAILED",
        "question": "VPN 無法連線怎麼辦？",
        "answer": "請先重新連線公司網路，再重新啟動 VPN。",
        "category": "VPN",
        "keywords": ["vpn", "connection"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "IT Service Desk",
        "issue_type_ids": ["vpn.connection_failed"],
        "audience_type": "GROUPS",
        "audience_group_ids": ["employees"],
    }

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/faqs",
            json=payload,
            headers={**writer_headers, "Idempotency-Key": "faq-create-1"},
        )
        assert created.status_code == 200
        faq = created.json()["faq"]
        version = created.json()["version"]
        faq_id, version_id = faq["faq_id"], version["version_id"]

        replay = client.post(
            "/api/faqs",
            json=payload,
            headers={**writer_headers, "Idempotency-Key": "faq-create-1"},
        )
        assert replay.status_code == 200
        assert replay.json()["faq"]["faq_id"] == faq_id

        positive = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/tests",
            json={
                "expected_etag": 1,
                "kind": "POSITIVE",
                "utterance": "我的 VPN 連不上",
                "expected_audience_group_ids": ["employees"],
            },
            headers=writer_headers,
        )
        assert positive.status_code == 200
        negative = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/tests",
            json={
                "expected_etag": 2,
                "kind": "NEGATIVE",
                "utterance": "我要重設密碼",
                "expected_audience_group_ids": ["employees"],
            },
            headers=writer_headers,
        )
        assert negative.status_code == 200

        stale = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/tests",
            json={
                "expected_etag": 1,
                "kind": "NEGATIVE",
                "utterance": "電腦無法開機",
            },
            headers=writer_headers,
        )
        assert stale.status_code == 409

        submitted = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/submit",
            json={"expected_etag": 3},
            headers=writer_headers,
        )
        assert submitted.status_code == 200
        denied_review = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/review",
            json={"expected_etag": 4, "approve": True, "reason": "checked"},
            headers=writer_headers,
        )
        assert denied_review.status_code == 403
        reviewed = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/review",
            json={"expected_etag": 4, "approve": True, "reason": "正反例與內容已確認"},
            headers=admin_headers,
        )
        assert reviewed.status_code == 200
        activated = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/activate",
            json={"expected_etag": 5, "reason": "發布固定答案"},
            headers=admin_headers,
        )
        assert activated.status_code == 200
        assert activated.json()["faq"]["status"] == "ACTIVE"

        edited_payload = {
            **payload,
            "answer": "請重新啟動 VPN；若仍失敗請聯絡 IT Service Desk。",
            "expected_etag": 6,
        }
        edited = client.put(
            f"/api/faqs/{faq_id}",
            json=edited_payload,
            headers=writer_headers,
        )
        assert edited.status_code == 200
        second_version_id = edited.json()["version"]["version_id"]
        assert second_version_id != version_id
        etag = edited.json()["faq"]["etag"]
        for kind, utterance in (
            ("POSITIVE", "公司 VPN 一直失敗"),
            ("NEGATIVE", "公司信箱密碼過期"),
        ):
            test_result = client.post(
                f"/api/faqs/{faq_id}/versions/{second_version_id}/tests",
                json={
                    "expected_etag": etag,
                    "kind": kind,
                    "utterance": utterance,
                    "expected_audience_group_ids": ["employees"],
                },
                headers=writer_headers,
            )
            assert test_result.status_code == 200
            etag = test_result.json()["faq"]["etag"]
        second_submitted = client.post(
            f"/api/faqs/{faq_id}/versions/{second_version_id}/submit",
            json={"expected_etag": etag},
            headers=writer_headers,
        )
        assert second_submitted.status_code == 200
        second_reviewed = client.post(
            f"/api/faqs/{faq_id}/versions/{second_version_id}/review",
            json={
                "expected_etag": second_submitted.json()["faq"]["etag"],
                "approve": True,
                "reason": "v2 正反例與內容已確認",
            },
            headers=admin_headers,
        )
        assert second_reviewed.status_code == 200
        second_activated = client.post(
            f"/api/faqs/{faq_id}/versions/{second_version_id}/activate",
            json={
                "expected_etag": second_reviewed.json()["faq"]["etag"],
                "reason": "發布 v2",
            },
            headers=admin_headers,
        )
        assert second_activated.status_code == 200
        rolled_back = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/rollback",
            json={
                "expected_etag": second_activated.json()["faq"]["etag"],
                "reason": "v2 regression",
            },
            headers=admin_headers,
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["faq"]["published_version_id"] == version_id
        assert rolled_back.json()["version"]["status"] == "ACTIVE"

        other_scope = {**writer_headers, "X-Backoffice-Owner-Units": "Finance"}
        assert client.get(f"/api/faqs/{faq_id}", headers=other_scope).status_code == 403
        assert client.get("/api/faqs", headers=other_scope).json()["items"] == []

    with TestClient(create_app(settings)) as restarted:
        detail = restarted.get(f"/api/faqs/{faq_id}", headers=admin_headers)
        assert detail.status_code == 200
        assert detail.json()["faq"]["status"] == "ACTIVE"
        assert detail.json()["faq"]["published_version_id"] == version_id
        assert len(detail.json()["versions"]) == 2
        assert len(detail.json()["tests"]) == 4
        assert len(detail.json()["audit"]) == 13
        disabled = restarted.post(
            f"/api/faqs/{faq_id}/disable",
            json={"expected_etag": 13, "reason": "內容暫停使用"},
            headers=admin_headers,
        )
        assert disabled.status_code == 200
        assert disabled.json()["faq"]["status"] == "DISABLED"


def test_phase2_examples_api_derives_source_and_persists(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
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
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        faq_store_path=tmp_path / "phase2" / "faqs.json",
        example_store_path=tmp_path / "phase2" / "examples.json",
    )
    writer_headers = {
        **headers("KNOWLEDGE_ADMIN"),
        "X-Backoffice-User-Id": "example.writer",
    }
    admin_headers = {
        **headers("SYSTEM_ADMIN"),
        "X-Backoffice-User-Id": "justin",
    }
    faq_payload = {
        "faq_key": "EXAMPLE_SOURCE_FAQ",
        "question": "VPN 無法連線怎麼辦？",
        "answer": "重新啟動 VPN。",
        "category": "VPN",
        "keywords": ["vpn"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "IT Service Desk",
        "issue_type_ids": ["vpn.connection_failed"],
        "audience_type": "ALL",
    }
    example_payload = {
        "text": "VPN user@example.com 無法連線",
        "expected_issue_type_id": "vpn.connection_failed",
        "expected_route": "FAQ",
        "label": "POSITIVE",
    }

    with TestClient(create_app(settings)) as client:
        faq_created = client.post("/api/faqs", json=faq_payload, headers=writer_headers)
        assert faq_created.status_code == 200
        faq_id = faq_created.json()["faq"]["faq_id"]
        version_id = faq_created.json()["version"]["version_id"]
        unknown_version = client.post(
            f"/api/faqs/{faq_id}/versions/unknown/examples",
            json=example_payload,
            headers=writer_headers,
        )
        assert unknown_version.status_code == 404
        forged_owner = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/examples",
            json={**example_payload, "owner_unit_id": "Finance"},
            headers=writer_headers,
        )
        assert forged_owner.status_code == 422
        created = client.post(
            f"/api/faqs/{faq_id}/versions/{version_id}/examples",
            json=example_payload,
            headers={**writer_headers, "Idempotency-Key": "example-create-1"},
        )
        assert created.status_code == 200
        example = created.json()["example"]
        example_id = example["example_id"]
        assert example["owner_unit_id"] == "IT Service Desk"
        assert example["source_version_id"] == version_id
        assert "user@example.com" not in example["text"]
        denied = client.post(
            f"/api/examples/{example_id}/review",
            json={"expected_etag": 1, "approve": True, "reason": "checked"},
            headers=writer_headers,
        )
        assert denied.status_code == 403
        verified = client.post(
            f"/api/examples/{example_id}/review",
            json={"expected_etag": 1, "approve": True, "reason": "Justin final approval"},
            headers=admin_headers,
        )
        assert verified.status_code == 200
        assert verified.json()["example"]["status"] == "VERIFIED"

    with TestClient(create_app(settings)) as restarted:
        detail = restarted.get(f"/api/examples/{example_id}", headers=admin_headers)
        assert detail.status_code == 200
        assert detail.json()["example"]["status"] == "VERIFIED"
        assert len(detail.json()["audit"]) == 2


def test_phase2_document_example_uses_scoped_inventory(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
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
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        example_store_path=tmp_path / "phase2" / "examples.json",
    )
    inventory = {
        "items": [
            {
                "documentId": "vpn-guide",
                "ownerUnitId": "IT Service Desk",
                "currentPublishedVersionId": "version-7",
                "draftVersionId": "version-8",
            }
        ],
        "portalStatus": "available",
    }
    payload = {
        "text": "VPN 指引沒有涵蓋錯誤 720",
        "expected_issue_type_id": "vpn.connection_failed",
        "expected_route": "KNOWLEDGE",
        "label": "NEGATIVE",
        "reason": "文件有內容缺口",
    }
    with patch.object(
        BackofficeQueryService,
        "list_documents",
        new=AsyncMock(return_value=inventory),
    ), TestClient(create_app(settings)) as client:
        invalid = client.post(
            "/api/knowledge/vpn-guide/versions/version-6/examples",
            json=payload,
            headers=headers("KNOWLEDGE_ADMIN"),
        )
        assert invalid.status_code == 404
        created = client.post(
            "/api/knowledge/vpn-guide/versions/version-7/examples",
            json=payload,
            headers=headers("KNOWLEDGE_ADMIN"),
        )
        assert created.status_code == 200
        example = created.json()["example"]
        assert example["source_type"] == "DOCUMENT"
        assert example["source_id"] == "vpn-guide"
        assert example["source_version_id"] == "version-7"
        assert example["owner_unit_id"] == "IT Service Desk"

    with patch.object(
        BackofficeQueryService,
        "list_documents",
        new=AsyncMock(return_value={"items": [], "portalStatus": "unavailable"}),
    ):
        response = TestClient(create_app(settings)).post(
            "/api/knowledge/vpn-guide/versions/version-7/examples",
            json=payload,
            headers=headers("KNOWLEDGE_ADMIN"),
        )
        assert response.status_code == 503


def test_phase2_conversation_example_derives_owner_and_correlation(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
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
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        example_store_path=tmp_path / "phase2" / "examples.json",
    )
    detail = {
        "conversationId": "conversation-1",
        "ownerUnitId": "IT Service Desk",
        "turns": [{"correlationId": "correlation-9"}],
    }
    payload = {
        "text": "VPN 還是連不上",
        "expected_issue_type_id": "vpn.connection_failed",
        "expected_route": "HANDOFF",
        "label": "POSITIVE",
    }
    with patch.object(
        BackofficeQueryService,
        "conversation_detail",
        new=AsyncMock(return_value=detail),
    ):
        response = TestClient(create_app(settings)).post(
            "/api/conversations/conversation-1/examples",
            json=payload,
            headers=headers("KNOWLEDGE_ADMIN"),
        )
    assert response.status_code == 200
    example = response.json()["example"]
    assert example["source_type"] == "CONVERSATION"
    assert example["owner_unit_id"] == "IT Service Desk"
    assert example["source_correlation_id"] == "correlation-9"


def test_phase2_quality_candidates_merge_case_and_gap_score(
    seeded_backoffice_client: TestClient,
) -> None:
    writer_headers = headers("KNOWLEDGE_ADMIN")
    owner_headers = headers("SERVICE_OWNER")
    refreshed = seeded_backoffice_client.post(
        "/api/quality-candidates/refresh",
        json={"days": 30},
        headers=writer_headers,
    )
    assert refreshed.status_code == 200
    candidates = refreshed.json()["items"]
    assert {item["case_type"] for item in candidates} >= {
        "NEGATIVE_FEEDBACK",
        "HANDOFF",
    }
    replay = seeded_backoffice_client.post(
        "/api/quality-candidates/refresh",
        json={"days": 30},
        headers=writer_headers,
    )
    assert replay.status_code == 200
    assert replay.json()["total"] == len(candidates)

    generated = seeded_backoffice_client.post(
        "/api/question-clusters/generate",
        headers=writer_headers,
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert len(payload["items"]) >= 1
    assert payload["groupingMethod"] == "OWNER_UNIT_ISSUE_TYPE"
    cluster = payload["items"][0]
    assert cluster["grouping_method"] == "OWNER_UNIT_ISSUE_TYPE"
    corrected = seeded_backoffice_client.post(
        "/api/question-clusters/correct",
        json={
            "cluster_ids": [cluster["cluster_id"]],
            "action": "RENAME",
            "name": "VPN 改善候選",
        },
        headers=writer_headers,
    )
    assert corrected.status_code == 200
    assert corrected.json()["items"][0]["revision"] == 2

    selected = [
        item["candidate_id"]
        for item in candidates
        if item["case_type"] in {"NEGATIVE_FEEDBACK", "HANDOFF"}
    ]
    merged = seeded_backoffice_client.post(
        "/api/quality-candidates/merge",
        json={
            "candidate_ids": selected,
            "title": "改善 VPN 回答與轉人工率",
            "description": "分析負評與轉人工原因",
            "priority": "HIGH",
            "assignee_id": "owner.demo",
        },
        headers=writer_headers,
    )
    assert merged.status_code == 200
    quality_case = merged.json()["case"]
    case_id = quality_case["case_id"]
    assert quality_case["frequency"] == len(selected)

    etag = quality_case["etag"]
    for status in ["TRIAGED", "IN_PROGRESS", "OBSERVING"]:
        transitioned = seeded_backoffice_client.post(
            f"/api/quality-cases/{case_id}/transition",
            json={"expected_etag": etag, "status": status, "reason": f"move to {status}"},
            headers=owner_headers,
        )
        assert transitioned.status_code == 200
        etag = transitioned.json()["case"]["etag"]
    resolved = seeded_backoffice_client.post(
        f"/api/quality-cases/{case_id}/transition",
        json={
            "expected_etag": etag,
            "status": "RESOLVED",
            "reason": "觀察期指標達標",
            "resolution_type": "FAQ_UPDATED",
        },
        headers=owner_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["case"]["resolved_at"]

    gaps = seeded_backoffice_client.get(
        "/api/gaps/summary?days=30",
        headers=owner_headers,
    )
    assert gaps.status_code == 200
    assert gaps.json()["scoreVersion"] == "gap-score-v1"
    assert gaps.json()["items"]
    assert set(gaps.json()["items"][0]["components"]) == {
        "frequency",
        "noAnswerRate",
        "negativeFeedbackRate",
        "handoffRate",
        "estimatedCostUsd",
    }


def test_phase2_sync_job_fails_closed_and_retries_after_restart(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
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
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        sync_store_path=tmp_path / "phase2" / "sync_jobs.json",
        sync_adapter_url=None,
    )
    writer_headers = headers("KNOWLEDGE_ADMIN")
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/sync-jobs",
            json={"scope_type": "ALL", "scope_ids": [], "reason": "full rebuild"},
            headers={**writer_headers, "Idempotency-Key": "sync-create-1"},
        )
        assert created.status_code == 200
        job_id = created.json()["job"]["job_id"]
        detail = client.get(f"/api/sync-jobs/{job_id}", headers=writer_headers)
        assert detail.status_code == 200
        assert detail.json()["job"]["status"] == "FAILED"
        assert detail.json()["job"]["error_summary"] == "SYNC_ADAPTER_UNAVAILABLE"
        assert [item["action"] for item in detail.json()["audit"]] == [
            "SYNC_REQUESTED",
            "SYNC_VALIDATING",
            "SYNC_FAILED",
        ]

    with TestClient(create_app(settings)) as restarted:
        retry = restarted.post(
            f"/api/sync-jobs/{job_id}/retry",
            json={"reason": "retry after adapter check"},
            headers={**writer_headers, "Idempotency-Key": "sync-retry-1"},
        )
        assert retry.status_code == 200
        retry_id = retry.json()["job"]["job_id"]
        retried = restarted.get(f"/api/sync-jobs/{retry_id}", headers=writer_headers)
        assert retried.json()["job"]["status"] == "FAILED"
        assert retried.json()["job"]["retry_of_job_id"] == job_id


def test_operations_summary_requires_auth(backoffice_client: TestClient) -> None:
    response = backoffice_client.get("/api/operations/summary")
    assert response.status_code == 401


def test_operations_summary_for_service_owner(backoffice_client: TestClient) -> None:
    response = backoffice_client.get("/api/operations/summary?days=7", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert "conversationCount" in body
    assert body["metricsDefinitionVersion"] == "v1"
    assert body["metricsSource"] == "event_scan"
    assert "aggregateCoverageComplete" in body


def test_daily_aggregates_rebuild_and_summary(seeded_backoffice_client: TestClient) -> None:
    from datetime import UTC, datetime, timedelta

    admin = headers("SYSTEM_ADMIN")
    rebuilt = seeded_backoffice_client.post(
        "/api/aggregates/rebuild?days=30",
        headers=admin,
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["written"] >= 1
    summary = seeded_backoffice_client.get(
        "/api/aggregates/summary?days=30",
        headers=admin,
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["source"] == "daily_aggregates"
    assert body["turnCount"] >= 1
    # Rolling windows stay on event_scan so partial leading days are not inflated.
    rolling = seeded_backoffice_client.get(
        "/api/operations/summary?days=30",
        headers=admin,
    ).json()
    assert rolling["metricsSource"] == "event_scan"
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    aligned = seeded_backoffice_client.get(
        "/api/operations/summary",
        headers=admin,
        params={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    ).json()
    assert aligned["metricsSource"] == "daily_aggregates"
    assert aligned["aggregateCoverageComplete"] is True
    # Scoped BU actors must not consume tenant-wide aggregates.
    scoped = seeded_backoffice_client.get(
        "/api/operations/summary?days=30",
        headers=headers("SERVICE_OWNER"),
    ).json()
    assert scoped["metricsSource"] == "event_scan"
    scoped_agg = seeded_backoffice_client.get(
        "/api/aggregates/summary?days=30",
        headers=headers("SERVICE_OWNER"),
    ).json()
    assert scoped_agg["source"] == "unavailable_for_scoped_actor"
    assert scoped_agg["coverageComplete"] is False


def test_taxonomy_endpoint(backoffice_client: TestClient) -> None:
    response = backoffice_client.get("/api/taxonomy", headers=headers("AI_ADMIN"))
    assert response.status_code == 200
    assert response.json()["taxonomyVersion"] == "v1"
    assert len(response.json()["items"]) >= 20


def test_auditor_cannot_read_summary(backoffice_client: TestClient) -> None:
    response = backoffice_client.get("/api/operations/summary", headers=headers("AUDITOR"))
    assert response.status_code == 403


def test_async_export_job(backoffice_client: TestClient) -> None:
    created = backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={"export_type": "operations_summary", "reason": "UAT export", "days": 7},
    )
    assert created.status_code == 200
    job_id = created.json()["jobId"]
    fetched = backoffice_client.get(f"/api/exports/{job_id}", headers=headers())
    assert fetched.status_code == 200
    assert fetched.json()["status"] in {"QUEUED", "RUNNING", "COMPLETED"}


def test_feedback_drill_down(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/feedback?days=30&rating=DOWN&handoff=true",
        headers=headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["conversationId"] == "conv-1"
    trace = item["trace"]
    assert trace["issueTypeId"] == "vpn.connection_failed"
    assert trace["documentIds"] == ["vpn-password-lockout"]
    assert trace["handoffOccurred"] is True


def test_feedback_cursor_pagination(seeded_backoffice_client: TestClient) -> None:
    first = seeded_backoffice_client.get(
        "/api/feedback?days=30&limit=1&cursor=0",
        headers=headers(),
    )
    assert first.status_code == 200
    assert first.json()["total"] == 2
    assert first.json()["nextCursor"] == "1"
    assert first.json()["hasMore"] is True

    second = seeded_backoffice_client.get(
        "/api/feedback?days=30&limit=1&cursor=1",
        headers=headers(),
    )
    assert second.status_code == 200
    assert second.json()["nextCursor"] is None
    assert second.json()["hasMore"] is False


def test_feedback_filters_by_traced_issue_type(
    seeded_backoffice_client: TestClient,
) -> None:
    matched = seeded_backoffice_client.get(
        "/api/feedback?days=30&issue_type_id=vpn.connection_failed",
        headers=headers(),
    )
    assert matched.status_code == 200
    assert matched.json()["total"] == 2

    unmatched = seeded_backoffice_client.get(
        "/api/feedback?days=30&issue_type_id=account.password_reset",
        headers=headers(),
    )
    assert unmatched.status_code == 200
    assert unmatched.json()["total"] == 0


def test_month_preset_starts_at_calendar_month() -> None:
    from datetime import UTC, datetime

    from ai_ops_backoffice.services.periods import resolve_period

    now = datetime(2026, 9, 20, 4, 30, tzinfo=UTC)
    with patch("ai_ops_backoffice.services.periods.utc_now", return_value=now):
        period = resolve_period(preset="month")

    assert period.preset == "month"
    assert period.explicit_range is True
    assert period.start_at.isoformat() == "2026-09-01T00:00:00+08:00"
    assert period.end_at == now


def test_document_performance(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/knowledge/vpn-password-lockout/performance?days=30",
        headers=headers("KNOWLEDGE_ADMIN"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["hitCount"] >= 1
    assert body["negativeFeedbackCount"] == 1
    assert body["releaseAttribution"][0]["releaseId"] == "release-2025-09-01"


def test_export_job_expires_after_ttl(tmp_path: Path) -> None:
    from datetime import timedelta

    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_authorization import (
        DevelopmentExportAuthorizationResolver,
    )
    from ai_ops_backoffice.services.export_content import MemoryExportContentStore
    from ai_ops_backoffice.services.export_service import ExportJob, ExportJobService

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="local-development",
    )
    resolver = DevelopmentExportAuthorizationResolver()
    resolver.register(actor=actor, tenant_id="local-development")
    content_store = MemoryExportContentStore()
    service = ExportJobService(
        audit_store=MemoryAuditStore(),
        store_path=tmp_path / "exports",
        environment="dev",
        content_store=content_store,
        authorization_resolver=resolver,
    )
    expired_at = (utc_now() - timedelta(hours=1)).isoformat()
    content_store.items["memory:job-expired"] = b"expired export"
    service._jobs["job-expired"] = ExportJob(
        job_id="job-expired",
        export_type="operations_summary",
        export_format="json",
        status="COMPLETED",
        reason="test",
        requested_by="owner.demo",
        requested_role="SERVICE_OWNER",
        days=7,
        created_at=expired_at,
        expires_at=expired_at,
        completed_at=expired_at,
        result={"conversationCount": 0},
        content_ref="memory:job-expired",
        content_type="application/json",
        tenant_id="local-development",
        requested_owner_units=("IT Service Desk",),
    )

    async def run() -> tuple[ExportJob | None, int]:
        await service._persist(service._jobs["job-expired"])
        removed = await service.purge_expired_jobs()
        return await service.get_job("job-expired", actor=actor), removed

    import asyncio

    job, removed = asyncio.run(run())
    assert removed == 1
    assert job is not None
    assert job.status == "EXPIRED"
    assert job.result is None
    assert content_store.items == {}


def test_routes_summary(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/routes/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["routeDistribution"][0]["route"] == "KNOWLEDGE"
    attribution = body["routeDistribution"][0]["attribution"]
    assert attribution["documentIds"] == [{"id": "vpn-password-lockout", "count": 1}]
    assert attribution["releaseIds"] == [{"id": "release-2025-09-01", "count": 1}]


def test_query_audit_recorded(seeded_backoffice_client: TestClient) -> None:
    seeded_backoffice_client.get("/api/operations/summary?days=7", headers=headers())
    audit = seeded_backoffice_client.get("/api/audit-events", headers=headers("AUDITOR"))
    actions = {item["action"] for item in audit.json()["items"]}
    assert "query.operations_summary" in actions


def test_file_audit_store_persists(tmp_path: Path) -> None:
    from agent_service.operations.audit import build_audit_event
    from agent_service.operations.audit_stores import FileAuditStore

    store = FileAuditStore(tmp_path / "audit")
    event = build_audit_event(
        actor_id="owner.demo",
        actor_role="SERVICE_OWNER",
        action="export.create",
        target_type="export_job",
        target_id="job-1",
    )

    async def run() -> None:
        await store.append(event)
        page, _ = await store.list_events(limit=10)
        assert len(page) == 1

    asyncio.run(run())
    assert (tmp_path / "audit" / "audit_events.jsonl").is_file()


def test_export_audit_on_download(backoffice_client: TestClient) -> None:
    created = backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={"export_type": "feedback", "reason": "Audit test", "days": 7},
    )
    job_id = created.json()["jobId"]
    for _ in range(20):
        fetched = backoffice_client.get(f"/api/exports/{job_id}", headers=headers())
        if fetched.json()["status"] == "COMPLETED":
            break
    download = backoffice_client.get(f"/api/exports/{job_id}/download", headers=headers())
    assert download.status_code == 200
    audit = backoffice_client.get("/api/audit-events", headers=headers("AUDITOR"))
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()["items"]}
    assert "export.create" in actions
    assert "export.download" in actions


def test_export_download_returns_csv_attachment(backoffice_client: TestClient) -> None:
    created = backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={
            "export_type": "operations_summary",
            "reason": "CSV download test",
            "days": 7,
            "export_format": "csv",
            "preset": "7d",
        },
    )
    job_id = created.json()["jobId"]
    for _ in range(20):
        fetched = backoffice_client.get(f"/api/exports/{job_id}", headers=headers())
        if fetched.json()["status"] == "COMPLETED":
            break
    download = backoffice_client.get(f"/api/exports/{job_id}/download", headers=headers())
    assert download.status_code == 200
    assert "text/csv" in download.headers.get("content-type", "")
    assert "attachment" in download.headers.get("content-disposition", "")


def test_header_auth_blocked_outside_dev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_DEPLOYMENT_ENV", "prod")
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
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
        entra_tenant_id=None,
        entra_client_id=None,
    )
    client = TestClient(create_app(settings))
    response = client.get("/api/operations/summary", headers=headers())
    assert response.status_code == 401


def test_entra_auth_accepts_bearer_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import base64
    import json

    monkeypatch.setenv("AI_OPS_ENTRA_VALIDATE_JWT", "false")
    payload = {
        "oid": "entra-user-1",
        "name": "Entra User",
        "roles": ["AI_OPS_SERVICE_OWNER"],
        "owner_units": "IT Service Desk",
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    token = f"header.{encoded}.signature"

    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="ENTRA",
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
        entra_tenant_id="tenant-demo",
        entra_client_id="client-demo",
    )
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/capabilities",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "SERVICE_OWNER"


def test_issue_routes_endpoint(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/issues/vpn.connection_failed/routes?days=30",
        headers=headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["issueTypeId"] == "vpn.connection_failed"
    assert body["routes"]


def test_export_audit_fail_closed(tmp_path: Path) -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit_errors import AuditWriteError
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_service import ExportJobService

    class FailingAuditStore(MemoryAuditStore):
        async def append(self, event) -> None:
            raise RuntimeError("audit unavailable")

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
    )
    service = ExportJobService(
        audit_store=FailingAuditStore(),
        store_path=tmp_path / "exports",
        environment="dev",
    )

    async def runner() -> dict[str, object]:
        return {"conversationCount": 0}

    import asyncio

    with pytest.raises(AuditWriteError):
        asyncio.run(
            service.create_job(
                actor=actor,
                export_type="operations_summary",
                reason="fail closed test",
                days=7,
                runner=runner,
            )
        )


def test_export_worker_failure_records_audit(tmp_path: Path) -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_service import ExportJobService

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
    )

    async def run() -> tuple[str, list]:
        audit_store = MemoryAuditStore()
        service = ExportJobService(
            audit_store=audit_store,
            store_path=tmp_path / "failed-exports",
            environment="dev",
        )

        async def runner() -> dict[str, object]:
            raise ValueError("invalid export data")

        job = await service.create_job(
            actor=actor,
            export_type="issues_summary",
            reason="failure audit test",
            days=7,
            runner=runner,
        )
        for _ in range(10):
            await asyncio.sleep(0)
            current = await service.get_job(job.job_id, actor=actor)
            if current and current.status == "FAILED":
                break
        events, _ = await audit_store.list_events()
        return current.status, events  # type: ignore[union-attr]

    status, events = asyncio.run(run())
    assert status == "FAILED"
    failure = next(event for event in events if event.action == "export.failed")
    assert failure.after["exportType"] == "issues_summary"
    assert failure.after["exportFormat"] == "json"
    assert failure.after["status"] == "FAILED"
    assert failure.after["attemptCount"] == 1
    assert failure.after["errorType"] == "ValueError"
    assert failure.after["workerId"]


def test_export_record_limit_fails_before_artifact_write(tmp_path: Path) -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_content import MemoryExportContentStore
    from ai_ops_backoffice.services.export_service import ExportJobService

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
    )

    async def run() -> tuple[str, str | None, dict[str, bytes]]:
        content_store = MemoryExportContentStore()
        service = ExportJobService(
            audit_store=MemoryAuditStore(),
            store_path=tmp_path / "limited-exports",
            environment="dev",
            content_store=content_store,
            max_records=1,
        )

        async def runner() -> dict[str, object]:
            return {
                "exportMetadata": {"recordCount": 2},
                "data": {"items": [{"id": "a"}, {"id": "b"}]},
            }

        job = await service.create_job(
            actor=actor,
            export_type="feedback",
            reason="record limit test",
            days=7,
            runner=runner,
        )
        for _ in range(10):
            await asyncio.sleep(0)
            current = await service.get_job(job.job_id, actor=actor)
            if current and current.status == "FAILED":
                break
        return current.status, current.error, content_store.items  # type: ignore[union-attr]

    status, error, artifacts = asyncio.run(run())
    assert status == "FAILED"
    assert error == "Export exceeds the maximum of 1 records."
    assert artifacts == {}


def test_export_rate_limiter_blocks_excess_requests() -> None:
    from ai_ops_backoffice.services.rate_limit import ExportRateLimiter, RateLimitExceeded

    limiter = ExportRateLimiter(max_exports_per_hour=1)
    limiter.check("owner.demo")
    with pytest.raises(RateLimitExceeded):
        limiter.check("owner.demo")


def test_reconciliation_matches_seeded_summary(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/admin/reconciliation/operations-summary?days=30",
        headers=headers("SYSTEM_ADMIN"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["allMatch"] is True
    assert body["eventCount"] >= 1
    assert all(item["match"] for item in body["checks"])


def test_costs_summary_groups_by_route_and_issue(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/costs/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["totalEstimatedCostUsd"] == 0.0025
    assert body["byRoute"][0]["route"] == "KNOWLEDGE"
    assert body["byRoute"][0]["estimatedCostUsd"] == 0.0025
    assert body["byIssueType"][0]["issueTypeId"] == "vpn.connection_failed"
    assert body["byIssueType"][0]["estimatedCostUsd"] == 0.0025


def test_issues_summary_includes_hierarchy(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/issues/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["hierarchy"]
    assert body["trends"]
    vpn_issue = next(
        item for item in body["items"] if item["issueTypeId"] == "vpn.connection_failed"
    )
    assert vpn_issue["negativeFeedbackRate"] == 1.0
    assert vpn_issue["handoffRate"] >= 1.0
    assert vpn_issue["estimatedCostUsd"] == 0.0025


def test_costs_summary_includes_twd(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/costs/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["totalEstimatedCostTwd"] > 0
    assert body["usdTwdExchangeRate"] == 31.70


def test_conversation_detail_includes_correlation_and_masking(
    seeded_backoffice_client: TestClient,
) -> None:
    response = seeded_backoffice_client.get("/api/conversations/conv-1", headers=headers())
    assert response.status_code == 200
    body = response.json()
    turn = body["turns"][0]
    assert turn["correlationId"] == "corr-1"
    assert turn["masked"] is True
    assert turn["issueTypeId"] == "vpn.connection_failed"
    assert turn["route"] == "KNOWLEDGE"
    assert turn["model"] == "gpt-4.1"
    assert turn["resultType"] == "KNOWLEDGE_ANSWERED"
    assert turn["answerMasked"]
    assert turn["feedbackRating"] == "DOWN"
    assert turn["resolvedStatus"] == "UNRESOLVED"
    assert turn["handoffStatus"] == "OFFERED"
    assert turn["resultType"] == "KNOWLEDGE_ANSWERED"
    assert turn["answerMasked"] == "請確認 VPN 密碼未鎖定後再試一次。"
    assert "vpn-password-lockout" in turn["documentIds"]


def test_conversation_unmask_requires_capability_and_reason(
    seeded_backoffice_client: TestClient,
) -> None:
    forbidden = seeded_backoffice_client.get(
        "/api/conversations/conv-1",
        headers=headers("SERVICE_OWNER"),
        params={"unmask_reason": "incident review"},
    )
    assert forbidden.status_code == 403

    short_reason = seeded_backoffice_client.get(
        "/api/conversations/conv-1",
        headers=headers("KNOWLEDGE_ADMIN"),
        params={"unmask_reason": "ab"},
    )
    assert short_reason.status_code == 400

    authorized = seeded_backoffice_client.get(
        "/api/conversations/conv-1",
        headers=headers("KNOWLEDGE_ADMIN"),
        params={"unmask_reason": "incident review"},
    )
    assert authorized.status_code == 200
    body = authorized.json()
    assert body["unmaskAuthorized"] is True
    assert body["turns"][0]["masked"] is False

    audit = seeded_backoffice_client.get("/api/audit-events", headers=headers("AUDITOR"))
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()["items"]}
    assert "query.conversation_unmasked" in actions


def test_capabilities_hide_restricted_nav_for_service_owner(
    seeded_backoffice_client: TestClient,
) -> None:
    response = seeded_backoffice_client.get("/api/capabilities", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert "ops.health.read" not in body["capabilities"]
    assert "ops.audit.read" not in body["capabilities"]
    assert "ops.knowledge.read" not in body["capabilities"]
    assert body["userId"] == "owner.demo"
    assert body["userName"] == "Owner Demo"
    assert body["displayName"] == "Owner Demo"
    assert "relaxedWorkflow" in body
    assert "minTestCasesForReview" in body


def test_xlsx_export_job_download(seeded_backoffice_client: TestClient) -> None:
    created = seeded_backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={
            "export_type": "costs_summary",
            "reason": "UAT xlsx export",
            "days": 30,
            "export_format": "xlsx",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["jobId"]
    for _ in range(20):
        fetched = seeded_backoffice_client.get(f"/api/exports/{job_id}", headers=headers())
        assert fetched.status_code == 200
        if fetched.json()["status"] == "COMPLETED":
            break
    assert fetched.json()["status"] == "COMPLETED"
    assert fetched.json()["hasArtifact"] is True
    assert "result" not in fetched.json()
    download = seeded_backoffice_client.get(
        f"/api/exports/{job_id}/download",
        headers=headers(),
    )
    assert download.status_code == 200
    assert download.content.startswith(b"PK")
    assert (
        download.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_operations_summary_includes_data_freshness(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/operations/summary?days=30", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["latestEventAt"] is not None
    assert body["dataFreshnessMinutes"] is not None


def test_reconciliation_costs_and_issues_match(seeded_backoffice_client: TestClient) -> None:
    costs = seeded_backoffice_client.get(
        "/api/admin/reconciliation/costs-summary?days=30",
        headers=headers("SYSTEM_ADMIN"),
    )
    assert costs.status_code == 200
    assert costs.json()["allMatch"] is True

    issues = seeded_backoffice_client.get(
        "/api/admin/reconciliation/issues-summary?days=30",
        headers=headers("SYSTEM_ADMIN"),
    )
    assert issues.status_code == 200
    assert issues.json()["allMatch"] is True


def test_admin_retention_purge_removes_expired_events(tmp_path: Path) -> None:
    import asyncio

    from agent_service.operations.contracts import OperationalEvent, utc_now

    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    asyncio.run(_seed_sample_events(store_path, data_dir))
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
    )
    client = TestClient(create_app(settings))
    ingestion = EventIngestionService(
        FileOperationalStore(store_path),
        _ops_settings(data_dir, store_path),
    )
    now = utc_now()

    async def add_expired_event() -> None:
        await ingestion.ingest(
            OperationalEvent(
                event_id="expired-turn",
                event_type="turn.received",
                occurred_at=now,
                correlation_id="corr-expired",
                retention_expires_at=now - timedelta(seconds=1),
                payload={"messageMasked": "expired"},
            )
        )

    asyncio.run(add_expired_event())
    forbidden = client.post("/api/admin/retention/purge", headers=headers())
    assert forbidden.status_code == 403

    response = client.post("/api/admin/retention/purge", headers=headers("SYSTEM_ADMIN"))
    assert response.status_code == 200
    assert response.json()["removed"] >= 1


def test_query_audit_fail_closed(tmp_path: Path) -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.audit_errors import AuditWriteError
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.query_audit import record_query_audit

    class FailingAuditStore(MemoryAuditStore):
        async def append(self, event) -> None:
            raise RuntimeError("audit unavailable")

    actor = ActorContext(
        user_id="owner.demo",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
    )

    async def run() -> None:
        await record_query_audit(
            FailingAuditStore(),
            actor=actor,
            action="query.operations_summary",
            target_id="operations_summary",
            environment="dev",
        )

    with pytest.raises(AuditWriteError):
        asyncio.run(run())


def test_conversations_filter_by_handoff(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get(
        "/api/conversations?days=30&handoff=true",
        headers=headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    assert body["items"][0]["conversationId"] == "conv-1"


def test_metrics_definitions_endpoint(seeded_backoffice_client: TestClient) -> None:
    response = seeded_backoffice_client.get("/api/metrics/definitions", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["definitions"]["conversation_count"]
    assert body["metricsDefinitionVersion"] == "v1"


def test_export_rejects_invalid_format(backoffice_client: TestClient) -> None:
    response = backoffice_client.post(
        "/api/exports",
        headers=headers(),
        json={
            "export_type": "operations_summary",
            "reason": "invalid format test",
            "days": 7,
            "export_format": "pdf",
        },
    )
    assert response.status_code == 400


def test_health_summary_simulated_anomalies(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        simulate_health_anomalies=True,
    )
    client = TestClient(create_app(settings))
    response = client.get("/api/health/summary", headers=headers("SYSTEM_ADMIN"))
    assert response.status_code == 200
    body = response.json()
    assert body["simulatedAnomalies"] is True
    statuses = {item["id"]: item["status"] for item in body["components"]}
    assert statuses["agent-service"] == "DEGRADED"
    assert statuses["agent-retrieval-search"] == "DOWN"
    assert statuses["ticket-service"] == "DOWN"


def test_health_summary_includes_active_knowledge_release(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    portal_response = MagicMock(status_code=200)
    release_response = MagicMock(status_code=200)
    release_response.json.return_value = [
        {
            "release_id": "release-2026-09-03",
            "status": "ACTIVE",
            "manifest": [{"document_id": "doc-1"}, {"document_id": "doc-2"}],
            "created_at": "2026-09-03T01:00:00+00:00",
            "activated_at": "2026-09-03T02:00:00+00:00",
            "index_setting_version": "index-v3",
        }
    ]
    http_client = MagicMock()
    http_client.__aenter__ = AsyncMock(return_value=http_client)
    http_client.__aexit__ = AsyncMock(return_value=False)
    http_client.get = AsyncMock(side_effect=[portal_response, release_response])

    with patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=http_client,
    ):
        response = TestClient(create_app(settings)).get(
            "/api/health/summary",
            headers=headers("SYSTEM_ADMIN"),
        )

    assert response.status_code == 200
    release = next(
        item for item in response.json()["components"]
        if item["id"] == "knowledge-release"
    )
    assert release == {
        "id": "knowledge-release",
        "status": "READY",
        "note": "Active Knowledge release is available.",
        "releaseId": "release-2026-09-03",
        "publishedAt": "2026-09-03T02:00:00+00:00",
        "indexStatus": "READY",
        "documentCount": 2,
        "indexSettingVersion": "index-v3",
        "telemetryStatus": "NO_DATA",
        "requestCount": 0,
        "availabilityRate": None,
        "errorRate": None,
        "timeoutRate": None,
        "p50LatencyMs": None,
        "p95LatencyMs": None,
    }


def test_health_summary_includes_24_hour_operational_metrics(
    seeded_backoffice_client: TestClient,
) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"retrieval": "ready", "chunks": 1, "hits": []}
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    with patch(
        "ai_ops_backoffice.services.query_service.httpx.AsyncClient",
        return_value=client,
    ):
        result = seeded_backoffice_client.get(
            "/api/health/summary",
            headers=headers("SYSTEM_ADMIN"),
        )

    assert result.status_code == 200
    body = result.json()
    assert body["telemetryWindowHours"] == 24
    components = {item["id"]: item for item in body["components"]}
    assert components["agent-service"]["requestCount"] == 1
    assert components["agent-service"]["availabilityRate"] == 1.0
    assert components["llm-api"]["requestCount"] == 1
    assert components["teams-adapter"]["telemetryStatus"] == "NO_DATA"


def test_health_summary_includes_recent_masked_anomalies(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    ingestion = EventIngestionService(
        FileOperationalStore(store_path),
        _ops_settings(data_dir, store_path),
    )

    async def seed_failure() -> None:
        await ingestion.ingest(
            OperationalEvent(
                event_id="request-failed-1",
                event_type="request.failed",
                occurred_at=utc_now(),
                correlation_id="corr-health-failure",
                payload={
                    "component": "knowledge_search",
                    "errorType": "UpstreamTimeout",
                    "message": "must not be returned",
                },
            )
        )

    asyncio.run(seed_failure())
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
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    result = TestClient(create_app(settings)).get(
        "/api/health/summary",
        headers=headers("SYSTEM_ADMIN"),
    )

    assert result.status_code == 200
    anomaly = result.json()["recentAnomalies"][0]
    assert anomaly == {
        "occurredAt": anomaly["occurredAt"],
        "component": "knowledge_search",
        "status": "TIMEOUT",
        "errorType": "UpstreamTimeout",
        "correlationId": "corr-health-failure",
    }


def test_health_metric_summary_separates_failures_and_timeouts() -> None:
    summary = BackofficeQueryService._health_metric_summary(
        [("SUCCESS", 100.0), ("FAILED", 200.0), ("TIMEOUT", 300.0)]
    )

    assert summary["requestCount"] == 3
    assert summary["availabilityRate"] == 0.3333
    assert summary["errorRate"] == 0.3333
    assert summary["timeoutRate"] == 0.3333
    assert summary["p50LatencyMs"] == 200.0


def test_operations_summary_rejects_excessive_custom_period(
    backoffice_client: TestClient,
) -> None:
    response = backoffice_client.get(
        "/api/operations/summary"
        "?start_date=2020-01-01T00:00:00%2B00:00"
        "&end_date=2026-01-01T00:00:00%2B00:00",
        headers=headers(),
    )
    assert response.status_code == 400
