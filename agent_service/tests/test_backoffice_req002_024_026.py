from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.stores.file_store import FileOperationalStore
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.budget_domain.models import AlertEvent
from ai_ops_backoffice.budget_domain.repository import InMemoryBudgetRepository
from ai_ops_backoffice.budget_domain.service import BudgetService
from ai_ops_backoffice.example_domain.models import ExampleRecord
from ai_ops_backoffice.example_domain.repository import InMemoryExampleRepository
from ai_ops_backoffice.example_domain.service import ExampleService
from ai_ops_backoffice.pricing_domain.repository import InMemoryPricingRepository
from ai_ops_backoffice.pricing_domain.service import PricingService
from ai_ops_backoffice.quality_domain.models import QualityCase
from ai_ops_backoffice.quality_domain.repository import InMemoryQualityRepository
from ai_ops_backoffice.quality_domain.service import QualityService
from ai_ops_backoffice.settings import BackofficeSettings
from ai_ops_backoffice.sync_domain.models import SyncJob
from ai_ops_backoffice.sync_domain.repository import InMemorySyncRepository
from ai_ops_backoffice.sync_domain.service import SyncService


def _make_settings(tmp_path: Path, ops_mode: str = "MEMORY") -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    return BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode=ops_mode,
        ops_store_path=store_path,
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="FILE",
        pricing_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT",
        entra_tenant_id=None,
        entra_client_id=None,
    )


def _client_for_test(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_make_settings(tmp_path, ops_mode="MEMORY")))


def _headers(role: str = "SYSTEM_ADMIN") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": "test.admin",
        "X-Backoffice-User-Name": "Test Admin",
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT",
    }


# ==============================================================================
# REQ-002: Token & Cost Statistics, Rates History, Audit Log, Cost Classification
# ==============================================================================


@pytest.mark.asyncio
async def test_pricing_service_mutations_audit_and_history() -> None:
    repo = InMemoryPricingRepository()
    service = PricingService(repo)
    actor = ActorContext(
        user_id="fin.ops",
        display_name="Finance Ops",
        role="AI_ADMIN",
        owner_unit_ids=("ALL",),
    )

    # Baseline rules loaded
    rates = service.list_rates()
    rates_map = {r["model"]: r for r in rates}
    assert "gemini-2.0-flash" in rates_map
    assert service.get_exchange_rate() == 31.70

    # Update model rate with before/after audit tracking
    await service.update_model_rate(
        model="gemini-2.0-flash",
        input_rate=0.20,
        output_rate=0.80,
        actor=actor,
        reason="Annual contract rate update",
    )
    lookup = service.lookup_rate("gemini-2.0-flash")
    assert lookup is not None
    assert lookup[0] == 0.20
    assert lookup[1] == 0.80

    # Update exchange rate
    await service.update_exchange_rate(
        exchange_rate=32.50,
        actor=actor,
        reason="Q3 currency adjustment",
    )
    assert service.get_exchange_rate() == 32.50

    # Verify changelog audit log contains before/after values
    history_data = service.list_history()
    audits = history_data["audits"]
    assert len(audits) >= 2

    rate_audit = next(c for c in audits if c["change_type"] == "MODEL_RATE")
    assert rate_audit["target_id"] == "gemini-2.0-flash"
    assert rate_audit["actor_id"] == "fin.ops"
    assert rate_audit["before"]["inputUsdPer1MTokens"] == 0.10
    assert rate_audit["after"]["inputUsdPer1MTokens"] == 0.20

    ex_audit = next(c for c in audits if c["change_type"] == "EXCHANGE_RATE")
    assert ex_audit["before"]["exchangeRate"] == 31.70
    assert ex_audit["after"]["exchangeRate"] == 32.50


def test_cost_rates_api_endpoints_and_rbac(tmp_path: Path) -> None:
    client = _client_for_test(tmp_path)

    # 1. Read rates
    res_get = client.get("/api/costs/rates", headers=_headers("SERVICE_OWNER"))
    assert res_get.status_code == 200
    rates_data = res_get.json()
    assert "rates" in rates_data
    assert rates_data["exchangeRateUsdToTwd"] == 31.70

    # 2. Mutate rate without ops.cost.write capability (SERVICE_OWNER) -> 403 Forbidden
    res_forbidden = client.post(
        "/api/costs/rates",
        headers=_headers("SERVICE_OWNER"),
        json={
            "model": "gemini-2.0-flash",
            "inputPerMillion": 0.25,
            "outputPerMillion": 0.90,
            "reason": "Unauthorized update",
        },
    )
    assert res_forbidden.status_code == 403

    # 3. Mutate rate with AI_ADMIN (has ops.cost.write) -> 200 Success
    res_ok = client.post(
        "/api/costs/rates",
        headers=_headers("AI_ADMIN"),
        json={
            "model": "gemini-2.0-flash",
            "inputPerMillion": 0.25,
            "outputPerMillion": 0.90,
            "reason": "Authorized price change",
        },
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["model"] == "gemini-2.0-flash"
    assert res_ok.json()["after"]["inputUsdPer1MTokens"] == 0.25
    assert res_ok.json()["after"]["outputUsdPer1MTokens"] == 0.90

    # 4. Read history
    res_hist = client.get("/api/costs/rates/history", headers=_headers("SERVICE_OWNER"))
    assert res_hist.status_code == 200
    history = res_hist.json()
    assert len(history["audits"]) >= 1
    assert history["audits"][0]["target_id"] == "gemini-2.0-flash"
    assert history["audits"][0]["change_type"] == "MODEL_RATE"


def test_cost_status_classification_estimated_zero_unknown(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, ops_mode="FILE")
    ingestion = EventIngestionService(FileOperationalStore(settings.ops_store_path), settings)
    now = datetime.now(UTC)

    # Ingest 3 usage events:
    # 1. Normal model (gpt-4.1) -> ESTIMATED
    # 2. Zero cost model (custom-free-model) -> ZERO_COST
    # 3. Unknown model (completely unconfigured) -> UNKNOWN
    events = [
        OperationalEvent(
            event_id="ev-1",
            event_type="usage.recorded",
            occurred_at=now,
            conversation_id="c1",
            correlation_id="corr-1",
            issue_type_id="vpn.connection_failed",
            payload={
                "model": "gpt-4.1",
                "inputTokens": 1000,
                "outputTokens": 500,
                "estimatedCostUsd": 0.007,
            },
        ),
        OperationalEvent(
            event_id="ev-2",
            event_type="usage.recorded",
            occurred_at=now,
            conversation_id="c2",
            correlation_id="corr-2",
            issue_type_id="vpn.connection_failed",
            payload={
                "model": "custom-free-model",
                "inputTokens": 2000,
                "outputTokens": 1000,
                "estimatedCostUsd": 0.0,
            },
        ),
        OperationalEvent(
            event_id="ev-3",
            event_type="usage.recorded",
            occurred_at=now,
            conversation_id="c3",
            correlation_id="corr-3",
            issue_type_id="vpn.connection_failed",
            payload={
                "model": "unregistered-unknown-llm",
                "inputTokens": 3000,
                "outputTokens": 1500,
                "estimatedCostUsd": None,
            },
        ),
    ]
    asyncio.run(ingestion.ingest_many(events))

    client = TestClient(create_app(settings))
    res = client.get("/api/costs/summary", headers=_headers("SYSTEM_ADMIN"))
    assert res.status_code == 200
    body = res.json()

    # Verify metrics classification
    assert body["estimatedCostEventCount"] == 1
    assert body["zeroCostEventCount"] == 1
    assert body["unknownCostEventCount"] == 1

    # Verify per-model costStatus
    model_status_map = {m["model"]: m["costStatus"] for m in body["byModel"]}
    assert model_status_map.get("gpt-4.1") == "ESTIMATED"
    assert model_status_map.get("custom-free-model") == "ZERO_COST"
    assert model_status_map.get("unregistered-unknown-llm") == "UNKNOWN"


# ==============================================================================
# REQ-024: System Health Monitoring & Historical Status vs Live Probe
# ==============================================================================


def test_health_summary_separates_historical_telemetry_from_live_probe(tmp_path: Path) -> None:
    client = _client_for_test(tmp_path)

    # 1. Today query (target_date omitted) -> normal live status
    res_today = client.get("/api/health/summary", headers=_headers("SYSTEM_ADMIN"))
    assert res_today.status_code == 200
    body_today = res_today.json()
    assert body_today["isHistorical"] is False
    assert body_today["historicalNotice"] is None

    # 2. Historical query (e.g. 2024-01-01) -> isHistorical is True and live probe is separated
    res_past = client.get("/api/health/summary?date=2024-01-01", headers=_headers("SYSTEM_ADMIN"))
    assert res_past.status_code == 200
    body_past = res_past.json()
    assert body_past["isHistorical"] is True
    assert "歷史日期" in (body_past["historicalNotice"] or "")

    components = {item["id"]: item for item in body_past["components"]}
    agent_comp = components["agent-service"]
    assert agent_comp["isHistorical"] is True
    assert "liveProbeStatus" in agent_comp
    # Historical status reflects no data for that past date, not today's probe
    assert agent_comp["status"] == "NO_DATA"


def test_health_summary_adapter_telemetry_aggregation(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, ops_mode="FILE")
    ingestion = EventIngestionService(FileOperationalStore(settings.ops_store_path), settings)
    now = datetime.now(UTC)

    # Ingest adapter inbound events
    events = [
        OperationalEvent(
            event_id="adapter-1",
            event_type="usage.recorded",
            occurred_at=now,
            conversation_id="conv-adapter-1",
            correlation_id="corr-adapter-1",
            payload={"component": "teams_adapter", "elapsedMs": 45.0, "status": "SUCCESS"},
        ),
        OperationalEvent(
            event_id="adapter-2",
            event_type="usage.recorded",
            occurred_at=now,
            conversation_id="conv-adapter-2",
            correlation_id="corr-adapter-2",
            payload={"component": "teams_adapter", "elapsedMs": 55.0, "status": "SUCCESS"},
        ),
    ]
    asyncio.run(ingestion.ingest_many(events))

    client = TestClient(create_app(settings))
    res = client.get("/api/health/summary", headers=_headers("SYSTEM_ADMIN"))
    assert res.status_code == 200
    components = {item["id"]: item for item in res.json()["components"]}
    adapter_comp = components["teams-adapter"]
    assert adapter_comp["telemetryStatus"] == "AVAILABLE"
    assert adapter_comp["requestCount"] == 2
    assert adapter_comp["availabilityRate"] == 1.0


# ==============================================================================
# REQ-026: Sensitive Data Masking, Data Governance & Cross-Domain Purge
# ==============================================================================


def test_example_domain_retention_start_and_purge() -> None:
    repo = InMemoryExampleRepository()
    service = ExampleService(repo, taxonomy=None)
    actor = ActorContext(
        user_id="qa.lead",
        display_name="QA Lead",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    now = datetime.now(UTC)
    old_time = now - timedelta(days=400)

    # 1. Active verified example (should NOT be purged)
    active_ex = ExampleRecord(
        example_id="ex-active",
        source_type="MANUAL",
        source_id="src-1",
        source_version_id=None,
        source_correlation_id=None,
        owner_unit_id="IT",
        text="Active knowledge test",
        expected_issue_type_id="vpn.connection_failed",
        expected_route="KNOWLEDGE",
        label="POSITIVE",
        status="VERIFIED",
        etag=1,
        created_by="qa",
        created_at=old_time,
        updated_by="qa",
        updated_at=old_time,
        retired_at=None,
    )
    # 2. Retired example past 365 days retention (should BE purged)
    retired_ex = ExampleRecord(
        example_id="ex-retired",
        source_type="MANUAL",
        source_id="src-2",
        source_version_id=None,
        source_correlation_id=None,
        owner_unit_id="IT",
        text="Retired knowledge test",
        expected_issue_type_id="vpn.connection_failed",
        expected_route="KNOWLEDGE",
        label="NEGATIVE",
        status="RETIRED",
        etag=1,
        created_by="qa",
        created_at=old_time - timedelta(days=30),
        updated_by="qa",
        updated_at=old_time,
        retired_at=old_time,
    )
    repo._save(repo._load().model_copy(update={"examples": (active_ex, retired_ex)}))

    purge_res = service.purge_expired(retention_days=365, actor=actor, now=now)
    assert purge_res["removed"] == 1
    assert purge_res["removed_ids"] == ["ex-retired"]

    # Active remains, retired is removed
    remaining = repo.list_examples()
    assert len(remaining) == 1
    assert remaining[0].example_id == "ex-active"


def test_quality_domain_retention_start_and_purge() -> None:
    repo = InMemoryQualityRepository()
    service = QualityService(repo)
    actor = ActorContext(
        user_id="qa.lead",
        display_name="QA Lead",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    now = datetime.now(UTC)
    old_time = now - timedelta(days=400)

    # Active case (NEW) vs Resolved case past retention
    active_case = QualityCase(
        case_id="case-active",
        title="Active Case",
        description="Investigation ongoing",
        case_type="NO_ANSWER",
        priority="MEDIUM",
        owner_unit_id="IT",
        status="IN_PROGRESS",
        etag=1,
        created_by="qa",
        created_at=old_time,
        updated_by="qa",
        updated_at=now,
    )
    resolved_case = QualityCase(
        case_id="case-resolved",
        title="Resolved Case",
        description="Fixed months ago",
        case_type="NO_ANSWER",
        priority="LOW",
        owner_unit_id="IT",
        status="RESOLVED",
        etag=1,
        created_by="qa",
        created_at=old_time - timedelta(days=20),
        updated_by="qa",
        updated_at=old_time,
        resolved_at=old_time,
    )
    state = repo.load().model_copy(update={"cases": (active_case, resolved_case), "revision": 1})
    repo._state = state

    purge_res = service.purge_expired(retention_days=365, actor=actor, now=now)
    assert purge_res["total"] == 1
    assert purge_res["purged_cases"] == 1

    remaining_cases = repo.load().cases
    assert len(remaining_cases) == 1
    assert remaining_cases[0].case_id == "case-active"


def test_sync_and_budget_domain_retention_purge() -> None:
    # 1. Sync domain
    sync_repo = InMemorySyncRepository()
    sync_service = SyncService(sync_repo)
    actor = ActorContext(
        user_id="sync.admin",
        display_name="Sync Admin",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    now = datetime.now(UTC)
    old_time = now - timedelta(days=400)

    active_job = SyncJob(
        job_id="job-active",
        scope_type="ALL",
        scope_key="all",
        requested_by="qa",
        owner_unit_id="IT",
        reason="nightly sync",
        status="BUILDING",
        correlation_id="corr-job-1",
        requested_at=now,
    )
    completed_job = SyncJob(
        job_id="job-old",
        scope_type="FAQ",
        scope_key="faq",
        requested_by="qa",
        owner_unit_id="IT",
        reason="old sync",
        status="COMPLETED",
        correlation_id="corr-job-2",
        requested_at=old_time - timedelta(hours=1),
        finished_at=old_time,
    )
    sync_state = sync_repo.load().model_copy(
        update={"jobs": (active_job, completed_job), "revision": 1}
    )
    sync_repo._state = sync_state

    sync_purge_res = sync_service.purge_expired(retention_days=365, actor=actor, now=now)
    assert sync_purge_res["total"] == 1
    assert sync_purge_res["purged_jobs"] == 1
    assert len(sync_repo.load().jobs) == 1
    assert sync_repo.load().jobs[0].job_id == "job-active"

    # 2. Budget domain
    budget_repo = InMemoryBudgetRepository()
    budget_service = BudgetService(budget_repo, notification_targets={"IT": "TEAMS"})

    open_alert = AlertEvent(
        alert_id="alert-open",
        severity="WARNING",
        scope_type="SERVICE",
        scope_id="agent-service",
        period_key="2026-09",
        suppression_key="suppress-1",
        status="OPEN",
        owner_unit_id="IT",
        first_triggered_at=now,
        last_triggered_at=now,
    )
    resolved_alert = AlertEvent(
        alert_id="alert-old",
        severity="CRITICAL",
        scope_type="SERVICE",
        scope_id="agent-service",
        period_key="2025-01",
        suppression_key="suppress-2",
        status="RESOLVED",
        owner_unit_id="IT",
        first_triggered_at=old_time - timedelta(days=5),
        last_triggered_at=old_time,
        resolved_at=old_time,
    )
    budget_state = budget_repo.load().model_copy(
        update={"alerts": (open_alert, resolved_alert), "revision": 1}
    )
    budget_repo._state = budget_state

    budget_purge_res = budget_service.purge_expired(retention_days=365, actor=actor, now=now)
    assert budget_purge_res["total"] == 1
    assert budget_purge_res["purged_alerts"] == 1
    assert len(budget_repo.load().alerts) == 1
    assert budget_repo.load().alerts[0].alert_id == "alert-open"


def test_retention_api_status_and_unified_purge_endpoint(tmp_path: Path) -> None:
    client = _client_for_test(tmp_path)

    # 1. GET /api/admin/retention/status
    res_status = client.get("/api/admin/retention/status", headers=_headers("SYSTEM_ADMIN"))
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert "policy" in status_data
    assert "domains" in status_data
    assert "dataStates" in status_data

    # Verify data state definitions include UNAUTHORIZED, MASKED, UNMASKED_WITH_REASON, EXPIRED_OR_PURGED
    state_codes = {s["code"] for s in status_data["dataStates"]}
    assert "UNAUTHORIZED" in state_codes
    assert "MASKED" in state_codes
    assert "UNMASKED_WITH_REASON" in state_codes
    assert "EXPIRED_OR_PURGED" in state_codes

    # 2. POST /api/admin/retention/purge
    res_purge = client.post("/api/admin/retention/purge", headers=_headers("SYSTEM_ADMIN"))
    assert res_purge.status_code == 200
    purge_data = res_purge.json()
    # Backward compatible removed key
    assert "removed" in purge_data
    # Domain breakdown
    assert "operationalEvents" in purge_data
    assert "exportJobs" in purge_data
    assert "examples" in purge_data
    assert "quality" in purge_data
    assert "sync" in purge_data
    assert "budget" in purge_data
    assert "totalRemoved" in purge_data


def test_conversation_data_state_masked_and_unmasked_with_reason(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, ops_mode="FILE")
    ingestion = EventIngestionService(FileOperationalStore(settings.ops_store_path), settings)
    now = datetime.now(UTC)

    event = OperationalEvent(
        event_id="turn-masked-1",
        event_type="turn.received",
        occurred_at=now,
        conversation_id="conv-masked-1",
        correlation_id="corr-masked-1",
        turn_id="turn-1",
        issue_type_id="vpn.connection_failed",
        payload={
            "userMessage": "My email is user@corp.example and inquiry ID is INQ-9988",
            "messageMasked": "My email is [REDACTED_EMAIL] and inquiry ID is [REDACTED_ID]",
        },
    )
    asyncio.run(ingestion.ingest_many([event]))

    client = TestClient(create_app(settings))

    # 1. Default read -> MASKED dataState
    res_masked = client.get("/api/conversations/conv-masked-1", headers=_headers("SYSTEM_ADMIN"))
    assert res_masked.status_code == 200
    conv_data = res_masked.json()
    assert conv_data["dataState"] == "MASKED"
    assert conv_data["unmaskAuthorized"] is False
    assert conv_data["turns"][0]["masked"] is True
    assert "[REDACTED_ID]" in conv_data["turns"][0]["userMessage"]
    assert "INQ-9988" not in conv_data["turns"][0]["userMessage"]

    # 2. Read with valid unmask_reason and capability -> UNMASKED_WITH_REASON dataState
    res_unmasked = client.get(
        "/api/conversations/conv-masked-1?unmask_reason=Security%20audit%20review",
        headers=_headers("SYSTEM_ADMIN"),
    )
    assert res_unmasked.status_code == 200
    unmasked_data = res_unmasked.json()
    assert unmasked_data["dataState"] == "UNMASKED_WITH_REASON"
    assert unmasked_data["unmaskAuthorized"] is True
    assert unmasked_data["turns"][0]["masked"] is False
    assert "INQ-9988" in unmasked_data["turns"][0]["userMessage"]
