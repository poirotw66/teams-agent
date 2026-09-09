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
from agent_service.usage import (
    configure_pricing_provider,
    convert_usd_to_twd,
    estimate_cost_usd,
    lookup_rate,
)
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.budget_domain.models import AlertEvent
from ai_ops_backoffice.budget_domain.repository import InMemoryBudgetRepository
from ai_ops_backoffice.budget_domain.service import BudgetService
from ai_ops_backoffice.example_domain.models import ExampleRecord
from ai_ops_backoffice.example_domain.repository import InMemoryExampleRepository
from ai_ops_backoffice.example_domain.service import ExampleService
from ai_ops_backoffice.pricing_domain.repository import (
    FirestorePricingRepository,
    InMemoryPricingRepository,
)
from ai_ops_backoffice.pricing_domain.service import PricingService
from ai_ops_backoffice.quality_domain.models import QualityCase
from ai_ops_backoffice.quality_domain.repository import InMemoryQualityRepository
from ai_ops_backoffice.quality_domain.service import QualityService
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.settings import BackofficeSettings
from ai_ops_backoffice.sync_domain.models import SyncJob
from ai_ops_backoffice.sync_domain.repository import InMemorySyncRepository
from ai_ops_backoffice.sync_domain.service import SyncService


def _make_settings(tmp_path: Path, ops_mode: str = "MEMORY", **overrides) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    store_path = tmp_path / "events"
    params = {
        "host": "127.0.0.1",
        "port": 8092,
        "service_token": "",
        "auth_mode": "HEADER",
        "ops_store_mode": ops_mode,
        "ops_store_path": store_path,
        "ops_taxonomy_path": data_dir / "ops" / "issue_taxonomy_v1.json",
        "ops_metrics_path": data_dir / "ops" / "metrics_definitions_v1.json",
        "ops_classification_rules_path": data_dir / "ops" / "issue_classification_rules.json",
        "ops_audit_store_mode": "FILE",
        "pricing_store_mode": "MEMORY",
        "knowledge_portal_url": "http://127.0.0.1:8091",
        "agent_api_url": "http://127.0.0.1:8000",
        "adapter_api_url": "http://127.0.0.1:3978",
        "ticket_service_url": None,
        "default_owner_unit_id": "IT",
        "entra_tenant_id": None,
        "entra_client_id": None,
    }
    params.update(overrides)
    return BackofficeSettings(**params)


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


@pytest.mark.asyncio
async def test_pricing_future_effective_date_and_auto_generated_version() -> None:
    repo = InMemoryPricingRepository()
    service = PricingService(repo)
    actor = ActorContext(
        user_id="fin.ops",
        display_name="Finance Ops",
        role="AI_ADMIN",
        owner_unit_ids=("ALL",),
    )
    now = datetime.now(UTC)
    future_time = now + timedelta(days=7)

    # 1. Update without version -> auto-generates version snapshot
    res_model = await service.update_model_rate(
        model="gpt-4o-mini",
        input_rate=0.20,
        output_rate=0.80,
        actor=actor,
        reason="Immediate rate adjustment without version",
    )
    auto_ver = res_model["after"]["pricingVersion"]
    assert auto_ver.startswith("2026-08-31.") or ".2" in auto_ver or "v1." in auto_ver
    assert service.get_pricing_version() == auto_ver

    after_step1 = datetime.now(UTC)

    # 2. Update with future effective date
    future_ver = "2026-Q4-future"
    future_time = after_step1 + timedelta(days=7)
    await service.update_model_rate(
        model="gpt-4o-mini",
        input_rate=0.50,
        output_rate=2.00,
        effective_at=future_time,
        pricing_version=future_ver,
        actor=actor,
        reason="Scheduled Q4 rate increase",
    )

    # Currently active (at step 1) must still be the previous rate, not the future rate
    current_lookup = service.lookup_rate("gpt-4o-mini", at=after_step1)
    assert current_lookup == (0.20, 0.80)
    assert service.get_pricing_version(at=after_step1) == auto_ver

    # At future time, the new rate activates
    future_lookup = service.lookup_rate("gpt-4o-mini", at=future_time + timedelta(hours=1))
    assert future_lookup == (0.50, 2.00)
    assert service.get_pricing_version(at=future_time + timedelta(hours=1)) == future_ver


@pytest.mark.asyncio
async def test_pricing_interleaved_rate_and_fx_schedules_preserve_timeline() -> None:
    """REQ-002/023: later FX snapshots must not wipe earlier scheduled model rates."""
    repo = InMemoryPricingRepository()
    service = PricingService(repo)
    actor = ActorContext(
        user_id="fin.ops",
        display_name="Finance Ops",
        role="AI_ADMIN",
        owner_unit_ids=("ALL",),
    )
    day0 = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    day7 = day0 + timedelta(days=7)
    day8 = day0 + timedelta(days=8)
    day9 = day0 + timedelta(days=9)

    # Schedule model rate for day 7 while current state still holds baseline rates.
    await service.update_model_rate(
        model="gpt-4o-mini",
        input_rate=9.0,
        output_rate=10.0,
        effective_at=day7,
        pricing_version="day7-model",
        actor=actor,
        reason="Day-7 model rate schedule",
    )
    # Schedule FX-only change for day 8; must inherit day-7 model rates from timeline.
    await service.update_exchange_rate(
        exchange_rate=35.0,
        effective_at=day8,
        pricing_version="day8-fx",
        actor=actor,
        reason="Day-8 FX schedule",
    )
    # Second model change after FX must keep FX 35 and update only that model.
    await service.update_model_rate(
        model="gemini-2.0-flash",
        input_rate=1.25,
        output_rate=5.0,
        effective_at=day9,
        pricing_version="day9-gemini",
        actor=actor,
        reason="Day-9 second model schedule",
    )

    assert service.lookup_rate("gpt-4o-mini", at=day7 + timedelta(hours=1)) == (9.0, 10.0)
    assert service.get_exchange_rate(at=day7 + timedelta(hours=1)) == 31.70

    assert service.lookup_rate("gpt-4o-mini", at=day8 + timedelta(hours=1)) == (9.0, 10.0)
    assert service.get_exchange_rate(at=day8 + timedelta(hours=1)) == 35.0
    assert service.get_pricing_version(at=day8 + timedelta(hours=1)) == "day8-fx"

    assert service.lookup_rate("gemini-2.0-flash", at=day9 + timedelta(hours=1)) == (1.25, 5.0)
    assert service.lookup_rate("gpt-4o-mini", at=day9 + timedelta(hours=1)) == (9.0, 10.0)
    assert service.get_exchange_rate(at=day9 + timedelta(hours=1)) == 35.0

    # Historical immutability: day-7 view must not observe day-8 FX.
    assert service.get_exchange_rate(at=day7 + timedelta(hours=1)) == 31.70
    history = service.list_history()
    # current* fields follow the effective timeline at "now" (after all schedules, still day0-ish
    # in wall clock). Use explicit effective queries for assertions above; history payload must
    # expose current fields from effective_rule_from_state rather than stale live state.
    assert "currentPricingVersion" in history
    assert "currentExchangeRate" in history
    day8_rule = next(r for r in history["history"] if r["version"] == "day8-fx")
    assert day8_rule["exchange_rate"] == 35.0
    assert day8_rule["rates"]["gpt-4o-mini"] == [9.0, 10.0] or day8_rule["rates"]["gpt-4o-mini"] == (
        9.0,
        10.0,
    )


@pytest.mark.asyncio
async def test_usage_module_integrates_with_governed_pricing_provider() -> None:
    repo = InMemoryPricingRepository()
    service = PricingService(repo)
    actor = ActorContext(
        user_id="fin.ops",
        display_name="Finance Ops",
        role="AI_ADMIN",
        owner_unit_ids=("ALL",),
    )

    await service.update_model_rate(
        model="custom-governed-llm",
        input_rate=2.0,
        output_rate=8.0,
        actor=actor,
        reason="Register governed rate",
    )
    await service.update_exchange_rate(
        exchange_rate=33.50,
        actor=actor,
        reason="Adjust USD/TWD rate",
    )

    configure_pricing_provider(service)
    try:
        assert lookup_rate("custom-governed-llm") == (2.0, 8.0)
        cost_usd = estimate_cost_usd("custom-governed-llm", input_tokens=1_000_000, output_tokens=500_000)
        assert cost_usd == 6.0  # 2.0*1 + 8.0*0.5 = 6.0 USD
        cost_twd = convert_usd_to_twd(10.0)
        assert cost_twd == 335.0  # 10.0 * 33.50
    finally:
        configure_pricing_provider(None)


@pytest.mark.asyncio
async def test_budget_usage_dynamic_exchange_rate_synchronization(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, ops_mode="FILE")
    ingestion = EventIngestionService(FileOperationalStore(settings.ops_store_path), settings)
    now = datetime.now(UTC)

    event = OperationalEvent(
        event_id="ev-budget-1",
        event_type="usage.recorded",
        occurred_at=now,
        conversation_id="conv-b1",
        correlation_id="corr-b1",
        actor_ref="user-123",
        issue_type_id="vpn.connection_failed",
        payload={
            "model": "gpt-4.1-mini",
            "inputTokens": 1_000_000,
            "outputTokens": 500_000,
            # Stale agent-side estimate must not override PricingService rates.
            "estimatedCostUsd": 1.0,
        },
    )
    await ingestion.ingest_many([event])

    query_svc = BackofficeQueryService(settings)
    actor = ActorContext(
        user_id="fin.ops",
        display_name="Finance Ops",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    await query_svc.pricing_service.update_exchange_rate(
        exchange_rate=35.00,
        actor=actor,
        reason="New exchange rate for budget test",
    )

    res = await query_svc.budget_usage(
        actor=actor,
        scope_type="PERSONAL",
        scope_id="user-123",
        period_type="DAILY",
        measure="TWD",
    )
    # Governed: (1M * 0.40 + 0.5M * 1.60) / 1M = 1.2 USD; * 35 FX = 42.0 TWD
    assert res["actualValue"] == 42.0
    assert res["pricingVersion"] == query_svc.pricing_service.get_pricing_version()
    assert res["exchangeRateVersion"] == res["pricingVersion"]


def test_firestore_pricing_repository_mock_transactions() -> None:
    class FakeDocSnapshot:
        def __init__(self, data: dict[str, Any] | None) -> None:
            self._data = data
            self.exists = data is not None

        def to_dict(self) -> dict[str, Any] | None:
            return self._data

    class FakeDocRef:
        def __init__(self) -> None:
            self.stored: dict[str, Any] | None = None

        def get(self, transaction: Any = None) -> FakeDocSnapshot:
            return FakeDocSnapshot(self.stored)

    class FakeCollectionRef:
        def __init__(self) -> None:
            self.docs: dict[str, FakeDocRef] = {}

        def document(self, name: str) -> FakeDocRef:
            if name not in self.docs:
                self.docs[name] = FakeDocRef()
            return self.docs[name]

    class FakeFirestoreClient:
        def __init__(self) -> None:
            self.collections: dict[str, FakeCollectionRef] = {}

        def collection(self, name: str) -> FakeCollectionRef:
            if name not in self.collections:
                self.collections[name] = FakeCollectionRef()
            return self.collections[name]

        def transaction(self) -> Any:
            return self

        def set(self, doc_ref: FakeDocRef, data: dict[str, Any]) -> None:
            doc_ref.stored = data

    fake_client = FakeFirestoreClient()

    def fake_transaction_runner(fn: Any, transaction: Any) -> Any:
        return fn(transaction)

    repo = FirestorePricingRepository(
        fake_client,
        collection="test_pricing_state",
        transaction_runner=fake_transaction_runner,
    )
    state = repo.load()
    assert state.revision == 1
    assert state.exchange_rate == 31.70

    def op(st: Any) -> tuple[Any, dict[str, Any]]:
        return st.model_copy(update={"revision": st.revision + 1, "exchange_rate": 34.0}), {"ok": True}

    res = repo.mutate(op)
    assert res["ok"] is True
    assert repo.load().exchange_rate == 34.0
    assert repo.load().revision == 2


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


def test_retention_status_uses_active_ttl_and_audit_exception(tmp_path: Path) -> None:
    from ai_ops_backoffice.retention_runtime import resolve_active_retention_ttls

    client = _client_for_test(tmp_path)
    app = client.app
    governance = app.state.governance_service
    admin = ActorContext(
        user_id="admin.a",
        display_name="Admin A",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    other = ActorContext(
        user_id="admin.b",
        display_name="Admin B",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    candidate = governance.create_retention_candidate(
        policy_id="operational-events",
        ttl_days=90,
        migration_plan="Shorten operational TTL to 90 days for lab verification.",
        reason="lab retention alignment",
        actor=admin,
    )
    version_id = candidate["policy"]["version_id"]
    governance.approve_retention(version_id=version_id, reason="peer approve", actor=other)
    governance.activate_retention(version_id=version_id, reason="activate short ttl", actor=admin)

    ttls = resolve_active_retention_ttls(governance)
    assert ttls["retention_days"] == 90
    assert ttls["audit_retention_days"] == 1095

    status = client.get("/api/admin/retention/status", headers=_headers("SYSTEM_ADMIN"))
    assert status.status_code == 200
    body = status.json()
    assert body["policy"]["ttlDays"] == 90
    assert body["auditRetentionDays"] == 1095
    assert body["domains"]["governance"]["retentionDays"] == 90
    assert body["domains"]["governance"]["auditRetentionDays"] == 1095
    assert body["domains"]["examples"]["retentionDays"] == 90

    purge = client.post("/api/admin/retention/purge", headers=_headers("SYSTEM_ADMIN"))
    assert purge.status_code == 200
    purge_body = purge.json()
    assert purge_body["retentionDays"] == 90
    assert purge_body["auditRetentionDays"] == 1095
    assert "governance" in purge_body
    assert purge_body["governance"].get("auditRetentionDays") == 1095


def test_governance_purge_keeps_audits_longer_than_versions() -> None:
    from ai_ops_backoffice.governance_domain.models import GovernanceAuditEvent
    from ai_ops_backoffice.governance_domain.repository import InMemoryGovernanceRepository
    from ai_ops_backoffice.governance_domain.service import GovernanceService

    repo = InMemoryGovernanceRepository()
    service = GovernanceService(repo)
    actor = ActorContext(
        user_id="gov.admin",
        display_name="Gov Admin",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    service.list_retention_policies(actor=actor)
    now = datetime.now(UTC)
    state = repo.load()
    aged_within_audit = GovernanceAuditEvent(
        audit_id="audit-within-audit-ttl",
        action="RETENTION_CANDIDATE_CREATED",
        actor_id=actor.user_id,
        actor_role=actor.role,
        target_type="RETENTION",
        target_id="operational-events",
        occurred_at=now - timedelta(days=400),
    )
    aged_beyond_audit = GovernanceAuditEvent(
        audit_id="audit-beyond-audit-ttl",
        action="RETENTION_CANDIDATE_CREATED",
        actor_id=actor.user_id,
        actor_role=actor.role,
        target_type="RETENTION",
        target_id="operational-events",
        occurred_at=now - timedelta(days=1200),
    )
    with repo._lock:
        repo._state = state.model_copy(
            update={
                "audits": (*state.audits, aged_within_audit, aged_beyond_audit),
            }
        )

    result = service.purge_expired(
        actor=actor,
        retention_days=90,
        audit_retention_days=1095,
        now=now,
    )
    assert result["auditRetentionDays"] == 1095
    remaining_ids = {a.audit_id for a in repo.load().audits}
    assert "audit-beyond-audit-ttl" not in remaining_ids
    assert "audit-within-audit-ttl" in remaining_ids


@pytest.mark.asyncio
async def test_budget_create_stamps_pricing_service_versions(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, ops_mode="FILE")
    app = create_app(settings)
    client = TestClient(app)
    actor = ActorContext(
        user_id="fin.ops",
        display_name="Finance",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    pricing = app.state.query_service.pricing_service
    await pricing.update_exchange_rate(
        exchange_rate=36.25,
        actor=actor,
        reason="Stamp budget policies with governed FX",
    )
    pricing_version = pricing.get_pricing_version()

    create = client.post(
        "/api/budget-policies",
        headers=_headers("SYSTEM_ADMIN"),
        json={
            "scope_type": "MODEL",
            "scope_id": "gpt-4.1",
            "period": "DAILY",
            "measure": "USD",
            "warning_threshold": 5.0,
            "critical_threshold": 10.0,
            "owner_unit_id": "IT",
            "notification_target_ids": ["notification-center"],
        },
    )
    assert create.status_code == 200
    policy = create.json()["policy"] if "policy" in create.json() else create.json()
    assert policy["pricing_version"] == pricing_version
    assert policy["exchange_rate_version"] == pricing_version

    usage = await app.state.query_service.budget_usage(
        actor,
        scope_type="MODEL",
        scope_id="gpt-4.1",
        period_type="DAILY",
        measure="TWD",
    )
    assert usage["pricingVersion"] == pricing_version
    assert usage["exchangeRateVersion"] == pricing_version


def test_health_taipei_day_boundary_for_utc_midnight_input(tmp_path: Path) -> None:
    from ai_ops_backoffice.services.query_health import resolve_taipei_day_window
    from zoneinfo import ZoneInfo

    # 2024-01-01T00:00:00Z is still 2024-01-01 morning in Taipei (+08)
    start, end, local_day = resolve_taipei_day_window("2024-01-01T00:00:00Z")
    assert str(local_day) == "2024-01-01"
    tz = ZoneInfo("Asia/Taipei")
    assert start.astimezone(tz).hour == 0
    assert (end - start) == timedelta(days=1)

    # Late UTC evening on Jan 1 maps to Taipei Jan 2
    start2, _end2, local_day2 = resolve_taipei_day_window("2024-01-01T20:00:00Z")
    assert str(local_day2) == "2024-01-02"
    assert start2.astimezone(tz).day == 2


@pytest.mark.asyncio
async def test_teams_and_index_emit_to_health_summary(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, ops_mode="FILE")
    query = BackofficeQueryService(settings)
    now = datetime.now(UTC)
    await query.record_component_usage(
        component="teams_adapter",
        status="SUCCESS",
        elapsed_ms=42.0,
        correlation_id="teams-e2e-1",
        payload={"attributionScope": "ADAPTER_REPLY"},
        occurred_at=now,
    )
    await query.record_component_usage(
        component="knowledge_index",
        status="SUCCESS",
        elapsed_ms=120.0,
        correlation_id="index-e2e-1",
        payload={"documentCount": 3},
        occurred_at=now,
    )
    summary = await query.health_summary()
    components = {item["id"]: item for item in summary["components"]}
    assert components["teams-adapter"]["telemetryStatus"] == "AVAILABLE"
    assert components["teams-adapter"]["requestCount"] >= 1
    assert components["teams-adapter"]["latencySampleCount"] >= 1
    assert components["agent-retrieval-index"]["telemetryStatus"] == "AVAILABLE"
    assert components["agent-retrieval-index"]["requestCount"] >= 1
    assert summary["monitoringScope"]["teamsAdapter"]["replySampleCount"] >= 1


@pytest.mark.asyncio
async def test_adapter_ingress_alone_is_not_reply_health(tmp_path: Path) -> None:
    """REQ-024: ADAPTER_INGRESS SUCCESS must not inflate teams-adapter availability."""
    settings = _make_settings(tmp_path, ops_mode="FILE")
    query = BackofficeQueryService(settings)
    now = datetime.now(UTC)
    await query.record_component_usage(
        component="teams_adapter",
        status="SUCCESS",
        correlation_id="ingress-only",
        payload={"attributionScope": "ADAPTER_INGRESS", "phase": "ingress"},
        occurred_at=now,
    )
    summary = await query.health_summary()
    components = {item["id"]: item for item in summary["components"]}
    assert components["teams-adapter"]["telemetryStatus"] == "NO_DATA"
    assert components["teams-adapter"]["requestCount"] == 0
    assert summary["monitoringScope"]["teamsAdapter"]["ingressSampleCount"] == 1
    assert "ADAPTER_INGRESS" in (components["teams-adapter"].get("note") or "")


@pytest.mark.asyncio
async def test_adapter_reply_fail_timeout_and_index_failure_boundaries(
    tmp_path: Path,
) -> None:
    """REQ-024 producer→store→health_summary for fail/timeout/empty history."""
    settings = _make_settings(tmp_path, ops_mode="FILE")
    query = BackofficeQueryService(settings)
    now = datetime.now(UTC)
    await query.record_component_usage(
        component="teams_adapter",
        status="SUCCESS",
        elapsed_ms=40.0,
        correlation_id="reply-ok",
        payload={"attributionScope": "ADAPTER_REPLY"},
        occurred_at=now,
    )
    await query.record_component_usage(
        component="teams_adapter",
        status="FAILED",
        elapsed_ms=80.0,
        correlation_id="reply-fail",
        payload={"attributionScope": "ADAPTER_REPLY", "errorType": "SendError"},
        occurred_at=now,
    )
    await query.record_component_usage(
        component="teams_adapter",
        status="TIMEOUT",
        elapsed_ms=10000.0,
        correlation_id="reply-timeout",
        payload={"attributionScope": "ADAPTER_REPLY", "errorType": "AgentGatewayTimeoutError"},
        occurred_at=now,
    )
    await query.record_component_usage(
        component="knowledge_index",
        status="FAILED",
        elapsed_ms=250.0,
        correlation_id="index-fail",
        payload={
            "attributionScope": "HEALTH_TELEMETRY",
            "errorType": "SYNC_ADAPTER_UNAVAILABLE",
        },
        occurred_at=now,
    )

    summary = await query.health_summary()
    components = {item["id"]: item for item in summary["components"]}
    adapter = components["teams-adapter"]
    assert adapter["requestCount"] == 3
    assert adapter["availabilityRate"] == pytest.approx(1 / 3, rel=1e-3)
    assert adapter["errorRate"] == pytest.approx(1 / 3, rel=1e-3)
    assert adapter["timeoutRate"] == pytest.approx(1 / 3, rel=1e-3)
    assert adapter["p50LatencyMs"] is not None
    assert adapter["latencySampleCount"] == 3

    index = components["agent-retrieval-index"]
    assert index["requestCount"] >= 1
    assert index["errorRate"] == 1.0
    assert index["latencySampleCount"] >= 1
    assert any(
        item["status"] == "TIMEOUT" and item["component"] == "teams_adapter"
        for item in summary["recentAnomalies"]
    )

    empty = await query.health_summary(target_date="2020-01-01")
    empty_components = {item["id"]: item for item in empty["components"]}
    assert empty_components["teams-adapter"]["status"] == "NO_DATA"
    assert empty_components["teams-adapter"]["telemetryStatus"] == "NO_DATA"


@pytest.mark.asyncio
async def test_sync_failure_emits_knowledge_index_failed_health(
    tmp_path: Path,
) -> None:
    """REQ-024: sync failure branch records knowledge_index FAILED + elapsedMs."""
    settings = _make_settings(tmp_path, ops_mode="FILE", sync_adapter_url="")
    app = create_app(settings)
    client = TestClient(app)
    sync_resp = client.post(
        "/api/sync-jobs",
        json={"scope_type": "ALL", "reason": "REQ-024 sync failure health"},
        headers=_headers("SYSTEM_ADMIN"),
    )
    assert sync_resp.status_code == 200

    health = client.get("/api/health/summary", headers=_headers("SYSTEM_ADMIN"))
    assert health.status_code == 200
    components = {item["id"]: item for item in health.json()["components"]}
    index = components["agent-retrieval-index"]
    assert index["telemetryStatus"] == "AVAILABLE"
    assert index["requestCount"] >= 1
    assert index["errorRate"] == 1.0
    assert index["latencySampleCount"] >= 1


@pytest.mark.asyncio
async def test_retention_sweep_worker_e2e_active_ttl_and_governance_purge(
    tmp_path: Path,
) -> None:
    """E2E: scheduled sweep function applies ACTIVE TTL and purges governance."""
    from ai_ops_backoffice.governance_domain.models import FlagVersion
    from ai_ops_backoffice.workers import run_scheduled_retention_sweep

    client = _client_for_test(tmp_path)
    app = client.app
    governance = app.state.governance_service
    admin = ActorContext(
        user_id="admin.a",
        display_name="Admin A",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    other = ActorContext(
        user_id="admin.b",
        display_name="Admin B",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
    )
    candidate = governance.create_retention_candidate(
        policy_id="operational-events",
        ttl_days=30,
        migration_plan="Activate 30-day TTL for scheduled sweep E2E.",
        reason="scheduled sweep e2e",
        actor=admin,
    )
    version_id = candidate["policy"]["version_id"]
    governance.approve_retention(version_id=version_id, reason="peer approve", actor=other)
    governance.activate_retention(version_id=version_id, reason="activate", actor=admin)

    now = datetime.now(UTC)
    expired_flag = FlagVersion(
        version_id="flag-expired-candidate",
        flag_id="ticket_mode",
        status="CANDIDATE",
        value="off",
        environment="lab",
        effective_at=now - timedelta(days=60),
        created_by="admin.a",
        created_at=now - timedelta(days=60),
        change_reason="old unused candidate",
    )

    def inject_expired(state):
        return state.model_copy(
            update={
                "revision": state.revision + 1,
                "flag_versions": (*state.flag_versions, expired_flag),
            }
        ), {"injected": True}

    governance._repository.mutate(inject_expired)
    assert any(
        v.version_id == "flag-expired-candidate"
        for v in governance._repository.load().flag_versions
    )

    sync_worker = ActorContext(
        user_id="ai-ops-sync-worker",
        display_name="AI Ops Sync Worker",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(),
    )
    result = await run_scheduled_retention_sweep(
        actor=sync_worker,
        query_service=app.state.query_service,
        sync_service=app.state.sync_service,
        budget_service=app.state.budget_service,
        example_service=app.state.example_service,
        quality_service=app.state.quality_service,
        governance_service=governance,
    )

    assert result["retentionDays"] == 30
    assert result["auditRetentionDays"] == 1095
    assert result["governance"]["retentionDays"] == 30
    assert result["governance"]["auditRetentionDays"] == 1095
    assert result["governance"]["flagVersions"] >= 1
    remaining = {v.version_id for v in governance._repository.load().flag_versions}
    assert "flag-expired-candidate" not in remaining
