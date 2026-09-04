"""P1 coverage: durable exports, masking rule packs, daily aggregates."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.masking import mask_text
from agent_service.operations.masking_rules import resolve_masking_pack
from agent_service.operations.policy_runtime import (
    PolicyRuntime,
    configure_policy_runtime,
    policy_snapshot_scope,
)
from agent_service.operations.settings import OpsSettings
from ai_ops_backoffice.governance_domain import FileGovernanceRepository, GovernanceService
from ai_ops_backoffice.services.daily_aggregates import build_daily_ops_aggregates
from ai_ops_backoffice.services.export_auth_store import FileBackedExportAuthorizationResolver
from ai_ops_backoffice.services.export_service import ExportJob, ExportJobService
from test_backoffice_governance_domain import AI, APPROVER


def _ops(tmp_path: Path) -> OpsSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    return OpsSettings(
        enabled=True,
        store_mode="MEMORY",
        store_path=tmp_path / "events",
        taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        environment="test",
        default_retention_days=365,
        transcript_retention_days=365,
        audit_retention_days=1095,
        async_emit=False,
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


@pytest.mark.asyncio
async def test_export_auth_registry_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "export_auth_registry.json"
    first = FileBackedExportAuthorizationResolver(path)
    actor = ActorContext(
        user_id="owner-1",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="local-development",
    )
    first.register(actor=actor, tenant_id="local-development")
    second = FileBackedExportAuthorizationResolver(path)
    resolved = await second.resolve(requester_id="owner-1", tenant_id="local-development")
    assert resolved is not None
    assert resolved.role == "SERVICE_OWNER"
    assert resolved.tenant_id == "local-development"


@pytest.mark.asyncio
async def test_export_job_recovers_queued_work(tmp_path: Path) -> None:
    from agent_service.operations.audit_stores import MemoryAuditStore

    class _Backend:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, *, actor: ActorContext, job: ExportJob) -> dict:
            self.calls += 1
            return {
                "ok": True,
                "exportMetadata": {"recordCount": 1, "fields": [], "queryFilters": {}},
            }

    audit = MemoryAuditStore()
    backend = _Backend()
    service = ExportJobService(
        audit_store=audit,
        store_path=tmp_path / "exports",
        environment="test",
        execution_backend=backend,
        run_inline=True,
    )
    actor = ActorContext(
        user_id="owner-1",
        display_name="Owner",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="local-development",
    )
    created = await service.create_job(
        actor=actor,
        export_type="operations_summary",
        reason="recover me",
        days=7,
        request_params={"period": {"days": 7}},
        idempotency_key="idem-1",
    )
    await service.wait_for_background_tasks()
    assert (await service.get_job(created.job_id, actor=actor)).status == "COMPLETED"

    # Simulate restart: new service, same store, recover interrupted (none) + idempotent create.
    restarted = ExportJobService(
        audit_store=audit,
        store_path=tmp_path / "exports",
        environment="test",
        execution_backend=backend,
        run_inline=True,
    )
    again = await restarted.create_job(
        actor=actor,
        export_type="operations_summary",
        reason="recover me",
        days=7,
        request_params={"period": {"days": 7}},
        idempotency_key="idem-1",
    )
    assert again.job_id == created.job_id
    assert backend.calls == 1


def test_masking_v3_changes_behavior(tmp_path: Path) -> None:
    gov = GovernanceService(FileGovernanceRepository(tmp_path / "gov.json"))
    created = gov.create_masking_candidate(policy_version="v3", reason="national id", actor=AI)
    version_id = created["policy"]["version_id"]
    gov.approve_masking(version_id=version_id, reason="ok", actor=APPROVER)
    gov.activate_masking(version_id=version_id, reason="go", actor=APPROVER)
    settings = _ops(tmp_path)
    runtime = PolicyRuntime(settings=settings, governance=gov)
    configure_policy_runtime(runtime)
    try:
        snapshot = runtime.snapshot()
        with policy_snapshot_scope(snapshot):
            assert snapshot.masking.policy_version == "v3"
            assert snapshot.masking.rules_hash == resolve_masking_pack("v3").rules_hash
            assert "[REDACTED_NATIONAL_ID]" in mask_text("id A123456789").text
    finally:
        configure_policy_runtime(None)


def test_daily_aggregate_scaffold() -> None:
    now = utc_now()
    events = [
        OperationalEvent(
            event_id="t1",
            event_type="turn.received",
            occurred_at=now,
            tenant_id="t",
            correlation_id="c1",
            environment="dev",
            payload={},
        ),
        OperationalEvent(
            event_id="i1",
            event_type="issue.extracted",
            occurred_at=now,
            tenant_id="t",
            correlation_id="c1",
            environment="dev",
            issue_type_id="vpn.connection_failed",
            payload={},
        ),
    ]
    aggregates = build_daily_ops_aggregates(events)
    assert len(aggregates) == 1
    assert aggregates[0].turn_count == 1
    assert aggregates[0].issue_count == 1
    assert aggregates[0].as_dict()["schemaVersion"] == "daily-ops-aggregate-v1"


def test_daily_aggregate_store_materialize_and_coverage(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from ai_ops_backoffice.services.daily_aggregates import (
        FileDailyAggregateStore,
        aggregates_cover_period,
        materialize_daily_aggregates,
        summarize_aggregates,
    )

    now = utc_now().replace(hour=12, minute=0, second=0, microsecond=0)
    events = [
        OperationalEvent(
            event_id=f"t-{index}",
            event_type="turn.received",
            occurred_at=now - timedelta(days=index),
            tenant_id="t",
            correlation_id=f"c-{index}",
            environment="dev",
            payload={},
        )
        for index in range(3)
    ]
    store = FileDailyAggregateStore(tmp_path / "daily_ops.json")
    written = materialize_daily_aggregates(events, store)
    assert written["written"] == 3
    rows = store.list_range(
        start_day=(now - timedelta(days=2)).date().isoformat(),
        end_day=now.date().isoformat(),
        environment="dev",
    )
    assert len(rows) == 3
    summary = summarize_aggregates(rows)
    assert summary["turnCount"] == 3
    period_start = datetime.combine(
        (now - timedelta(days=2)).date(),
        datetime.min.time(),
        tzinfo=UTC,
    )
    period_end = datetime.combine(
        (now + timedelta(days=1)).date(),
        datetime.min.time(),
        tzinfo=UTC,
    )
    assert aggregates_cover_period(
        rows,
        start_at=period_start,
        end_at=period_end,
        environment="dev",
    )


@pytest.mark.asyncio
async def test_export_atomic_claim_is_exclusive(tmp_path: Path) -> None:
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_job_store import FileExportJobStore

    store = FileExportJobStore(tmp_path / "jobs")
    await store.put(
        "job-1",
        {
            "job_id": "job-1",
            "export_type": "operations_summary",
            "export_format": "json",
            "status": "QUEUED",
            "reason": "mutex",
            "requested_by": "a",
            "requested_role": "SERVICE_OWNER",
            "days": 7,
            "created_at": utc_now().isoformat(),
            "expires_at": utc_now().isoformat(),
            "tenant_id": "tenant-a",
            "attempt_count": 0,
        },
    )
    now = utc_now()
    first = await store.claim_job("job-1", worker_id="w1", lease_seconds=60, now=now)
    second = await store.claim_job("job-1", worker_id="w2", lease_seconds=60, now=now)
    assert first is not None
    assert first["lease_owner"] == "w1"
    assert second is None


@pytest.mark.asyncio
async def test_export_idempotency_scoped_to_tenant_and_requester(tmp_path: Path) -> None:
    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_authorization import ExportIdempotencyConflictError

    class _Backend:
        calls = 0

        async def execute(self, *, actor, job):
            self.calls += 1
            return {
                "ok": True,
                "exportMetadata": {"recordCount": 1, "fields": [], "queryFilters": {}},
            }

    audit = MemoryAuditStore()
    backend = _Backend()
    service = ExportJobService(
        audit_store=audit,
        store_path=tmp_path / "exports",
        environment="test",
        execution_backend=backend,
        run_inline=True,
    )
    alice = ActorContext(
        user_id="alice",
        display_name="Alice",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="tenant-a",
    )
    bob = ActorContext(
        user_id="bob",
        display_name="Bob",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="tenant-b",
    )
    first = await service.create_job(
        actor=alice,
        export_type="operations_summary",
        reason="same key",
        days=7,
        request_params={"period": {"days": 7}},
        idempotency_key="shared-key",
    )
    await service.wait_for_background_tasks()
    other = await service.create_job(
        actor=bob,
        export_type="operations_summary",
        reason="same key",
        days=7,
        request_params={"period": {"days": 7}},
        idempotency_key="shared-key",
    )
    assert other.job_id != first.job_id
    with pytest.raises(ExportIdempotencyConflictError):
        await service.create_job(
            actor=alice,
            export_type="operations_summary",
            reason="different params",
            days=30,
            request_params={"period": {"days": 30}},
            idempotency_key="shared-key",
        )


@pytest.mark.asyncio
async def test_export_mid_crash_lease_takeover(tmp_path: Path) -> None:
    from datetime import timedelta

    from agent_service.operations.audit_stores import MemoryAuditStore
    from ai_ops_backoffice.services.export_job_store import FileExportJobStore

    store = FileExportJobStore(tmp_path / "jobs")
    expired = (utc_now() - timedelta(seconds=5)).isoformat()
    await store.put(
        "job-crash",
        {
            "job_id": "job-crash",
            "export_type": "operations_summary",
            "export_format": "json",
            "status": "RUNNING",
            "reason": "crash",
            "requested_by": "a",
            "requested_role": "SERVICE_OWNER",
            "days": 7,
            "created_at": utc_now().isoformat(),
            "expires_at": (utc_now() + timedelta(days=1)).isoformat(),
            "tenant_id": "tenant-a",
            "attempt_count": 1,
            "lease_owner": "dead-worker",
            "lease_expires_at": expired,
            "lease_token": "old-token",
        },
    )
    claimed = await store.claim_job(
        "job-crash",
        worker_id="survivor",
        lease_seconds=60,
        now=utc_now(),
    )
    assert claimed is not None
    assert claimed["lease_owner"] == "survivor"
    assert claimed["attempt_count"] == 2
    assert claimed["lease_token"] != "old-token"

    completed = {
        **claimed,
        "status": "COMPLETED",
        "completed_at": utc_now().isoformat(),
    }
    assert await store.complete_if_owner(
        "job-crash",
        worker_id="survivor",
        lease_token=claimed["lease_token"],
        payload=completed,
    )
    assert not await store.complete_if_owner(
        "job-crash",
        worker_id="dead-worker",
        lease_token="old-token",
        payload=completed,
    )


@pytest.mark.asyncio
async def test_export_auth_reloads_shared_registry_and_authority(tmp_path: Path) -> None:
    from ai_ops_backoffice.services.export_authorization import GovernanceRevocationAuthority

    path = tmp_path / "auth.json"
    alice = ActorContext(
        user_id="alice",
        display_name="Alice",
        role="SERVICE_OWNER",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="tenant-a",
    )
    writer = FileBackedExportAuthorizationResolver(path)
    writer.register(actor=alice, tenant_id="tenant-a")

    revoked: set[str] = set()
    reader = FileBackedExportAuthorizationResolver(
        path,
        authority=GovernanceRevocationAuthority(lambda: revoked),
    )
    resolved = await reader.resolve(requester_id="alice", tenant_id="tenant-a")
    assert resolved is not None
    assert resolved.role == "SERVICE_OWNER"

    revoked.add("alice")
    assert await reader.resolve(requester_id="alice", tenant_id="tenant-a") is None


def test_governance_store_factory_accepts_sharded_mode(tmp_path: Path) -> None:
    from ai_ops_backoffice.governance_domain.store_factory import (
        build_governance_repository,
        normalize_governance_store_mode,
    )

    assert normalize_governance_store_mode("FIRESTORE_SHARDED") == "FIRESTORE_SHARDED"
    repo = build_governance_repository(
        store_mode="FILE",
        file_path=tmp_path / "gov.json",
    )
    assert repo.load().revision == 0
