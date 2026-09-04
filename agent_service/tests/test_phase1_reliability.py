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
    bind_policy_snapshot,
    configure_policy_runtime,
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
        bind_policy_snapshot(snapshot)
        assert snapshot.masking.policy_version == "v3"
        assert snapshot.masking.rules_hash == resolve_masking_pack("v3").rules_hash
        assert "[REDACTED_NATIONAL_ID]" in mask_text("id A123456789").text
    finally:
        bind_policy_snapshot(None)
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
            payload={},
        ),
        OperationalEvent(
            event_id="i1",
            event_type="issue.extracted",
            occurred_at=now,
            tenant_id="t",
            correlation_id="c1",
            issue_type_id="vpn.connection_failed",
            payload={},
        ),
    ]
    aggregates = build_daily_ops_aggregates(events)
    assert len(aggregates) == 1
    assert aggregates[0].turn_count == 1
    assert aggregates[0].issue_count == 1
    assert aggregates[0].as_dict()["schemaVersion"] == "daily-ops-aggregate-v1"
