from __future__ import annotations

import concurrent.futures
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.evaluation_domain.errors import (
    EvaluationVersionConflictError,
    JobFencingConflictError,
    JobLeaseLostError,
)
from ai_ops_backoffice.evaluation_domain.gate_models import (
    EvalSchedule,
    GateDecision,
    GatePolicy,
    GatePolicyVersion,
)
from ai_ops_backoffice.evaluation_domain.gate_repository import FileQualityGateRepository
from ai_ops_backoffice.evaluation_domain.job_models import ExecutionJob
from ai_ops_backoffice.evaluation_domain.job_repository import (
    FileJobRepository,
    InMemoryJobRepository,
)
from ai_ops_backoffice.evaluation_domain.job_worker import ExecutionJobWorker
from ai_ops_backoffice.evaluation_domain.migration import EvaluationMigrationTool
from ai_ops_backoffice.evaluation_domain.models import (
    CaseRevision,
    CriterionItem,
    EvalCase,
    EvaluationCriteria,
    EvaluationState,
    ProvenanceSpec,
    ToolConstraintsSpec,
    calculate_revision_content_hash,
)
from ai_ops_backoffice.evaluation_domain.repository import (
    FileEvaluationRepository,
    InMemoryEvaluationRepository,
)
from ai_ops_backoffice.evaluation_domain.runner import EvaluationRunner
from ai_ops_backoffice.evaluation_domain.runner_models import (
    EvaluationRun,
    TargetManifest,
)
from ai_ops_backoffice.evaluation_domain.tool_fixture_models import ToolFixture
from ai_ops_backoffice.evaluation_domain.tool_fixtures import (
    FileToolFixtureRepository,
    ToolFixtureService,
)
from ai_ops_backoffice.settings import BackofficeSettings


def _make_actor(user_id: str = "u-admin", role: str = "SYSTEM_ADMIN") -> ActorContext:
    return ActorContext(
        user_id=user_id,
        role=role,
        tenant_id="tenant-1",
        owner_unit_id="IT Service Desk",
        capabilities=(
            "ops.evals.read",
            "ops.evals.author",
            "ops.evals.review",
            "ops.evals.run",
            "ops.gate.manage",
        ),
    )


def test_a01_t1_persistence_across_restart(tmp_path: Path) -> None:
    """A01-T1: Restart API/worker keeps EvalCase, Fixture, Gate, Schedule, and Run states intact."""
    eval_file = tmp_path / "golden_evals.json"
    gate_dir = tmp_path / "gates"
    fixture_dir = tmp_path / "fixtures"
    job_dir = tmp_path / "jobs"

    now = datetime.now(UTC)

    # 1. First instance writes entities
    eval_repo = FileEvaluationRepository(eval_file)
    gate_repo = FileQualityGateRepository(gate_dir)
    fixture_repo = FileToolFixtureRepository(fixture_dir)
    job_repo = FileJobRepository(job_dir)

    # Write Case
    crit = EvaluationCriteria(
        required_facts=(CriterionItem(criterion_id="c1", description="fact 1"),),
        reference_answer="test answer",
    )
    chash = calculate_revision_content_hash(
        query="what is vpn?",
        criteria=crit,
        evidence=(),
        behavior="ANSWER_WITH_CITATION",
        tool_constraints=ToolConstraintsSpec(),
        tags=("vpn",),
        criticality="NORMAL",
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="src-1"),
    )
    rev = CaseRevision(
        revision_id="rev-1",
        case_id="case-1",
        revision_number=1,
        query="what is vpn?",
        criteria=crit,
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="src-1"),
        etag=1,
        content_hash=chash,
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    case = EvalCase(
        case_id="case-1",
        tenant_id="tenant-1",
        owner_unit_id="IT Service Desk",
        title="VPN Setup",
        current_revision_id="rev-1",
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    manifest = TargetManifest(
        target_id="tgt-1",
        target_side="BASELINE",
        manifest_hash="hash-1",
    )
    run = EvaluationRun(
        run_id="run-1",
        tenant_id="tenant-1",
        owner_unit_id="IT Service Desk",
        set_version_id="sv-1",
        baseline_manifest=manifest,
        candidate_manifest=manifest,
        requested_by="tester",
        created_at=now,
    )
    new_state = EvaluationState(
        cases=(case,),
        revisions=(rev,),
        runs=(run,),
    )
    eval_repo.commit_mutation(new_state)

    # Write Gate policy & Schedule
    policy = GatePolicy(
        policy_id="pol-1",
        tenant_id="tenant-1",
        name="Production Gate",
        current_version=1,
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    gate_repo.save_policy(policy)

    schedule = EvalSchedule(
        schedule_id="sched-1",
        tenant_id="tenant-1",
        name="Nightly Run",
        set_version_id="sv-1",
        revision=1,
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    gate_repo.save_schedule(schedule)

    # Write Fixture
    fixture = ToolFixture(
        fixture_id="fix-1",
        tenant_id="tenant-1",
        tool_name="get_ticket",
        current_version=1,
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    fixture_repo.save_fixture(fixture)

    # Write Job
    job = ExecutionJob(
        tenant_id="tenant-1",
        job_id="job-1",
        run_id="run-1",
        logical_key="run:tenant-1:run-1",
        state="QUEUED",
        created_at=now,
        updated_at=now,
    )
    job_repo.enqueue_job(job)

    # 2. Simulate restart with new repository instances pointing to same storage
    eval_repo2 = FileEvaluationRepository(eval_file)
    gate_repo2 = FileQualityGateRepository(gate_dir)
    fixture_repo2 = FileToolFixtureRepository(fixture_dir)
    job_repo2 = FileJobRepository(job_dir)

    # Verify everything reloaded correctly
    assert eval_repo2.get_case("case-1") is not None
    assert eval_repo2.get_case("case-1").title == "VPN Setup"
    assert eval_repo2.get_revision("rev-1") is not None
    assert eval_repo2.get_run("run-1") is not None

    loaded_policy = gate_repo2.get_policy("pol-1")
    assert loaded_policy is not None
    assert loaded_policy.name == "Production Gate"

    loaded_sched = gate_repo2.get_schedule("sched-1")
    assert loaded_sched is not None
    assert loaded_sched.name == "Nightly Run"

    loaded_fix = fixture_repo2.get_fixture("fix-1")
    assert loaded_fix is not None
    assert loaded_fix.tool_name == "get_ticket"

    loaded_job = job_repo2.get_job("job-1")
    assert loaded_job is not None
    assert loaded_job.state == "QUEUED"


def test_a02_t1_concurrent_writes_and_cas(tmp_path: Path) -> None:
    """A02-T1: Concurrent updates with matching revisions reject stale writes with CAS conflict."""
    gate_dir = tmp_path / "gates"
    gate_repo = FileQualityGateRepository(gate_dir)

    now = datetime.now(UTC)
    version = GatePolicyVersion(
        policy_id="pol-c",
        version=1,
        name="Version 1",
        etag=1,
        created_by="tester",
        created_at=now,
    )
    gate_repo.save_version(version)

    # Two concurrent updates attempting to mutate etag 1
    def update_with_expected(worker_id: str, expected_etag: int, new_name: str) -> bool:
        try:
            current = gate_repo.get_version("pol-c", 1)
            updated = current.model_copy(
                update={"name": new_name, "etag": current.etag + 1}
            )
            gate_repo.save_version(updated, expected_etag=expected_etag)
            return True
        except EvaluationVersionConflictError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(update_with_expected, "w1", 1, "Name from W1")
        f2 = executor.submit(update_with_expected, "w2", 1, "Name from W2")
        results = [f1.result(), f2.result()]

    # Exactly one succeeded, one failed with conflict
    assert results.count(True) == 1
    assert results.count(False) == 1


def test_a03_t1_crash_recovery_and_fencing(tmp_path: Path) -> None:
    """A03-T1: Expired lease re-claimed; old worker heartbeat or completion rejected by fencing token."""
    job_dir = tmp_path / "jobs"
    job_repo = FileJobRepository(job_dir)

    now = datetime.now(UTC)
    job = ExecutionJob(
        tenant_id="tenant-1",
        job_id="job-crash",
        run_id="run-crash",
        logical_key="run:tenant-1:run-crash",
        state="QUEUED",
        created_at=now,
        updated_at=now,
    )
    job_repo.enqueue_job(job)

    # Worker 1 claims job with 1-second lease
    claimed1 = job_repo.claim_job("worker-1", lease_seconds=1.0)
    assert claimed1 is not None
    assert claimed1.lease_owner == "worker-1"
    token1 = claimed1.fencing_token

    # Simulate worker-1 crash: worker-1 stops heartbeating and lease expires
    # Time travels: lease_until is set in the past
    expired_job = claimed1.model_copy(
        update={"lease_until": now - timedelta(seconds=10)}
    )
    # Force expire in storage
    job_repo._write_record_atomic(expired_job)
    job_repo._sync_from_disk()

    # Worker 2 discovers and re-claims expired job
    claimed2 = job_repo.claim_job("worker-2", lease_seconds=60.0)
    assert claimed2 is not None
    assert claimed2.lease_owner == "worker-2"
    assert claimed2.fencing_token > token1

    # Zombie worker 1 comes back and tries to heartbeat or complete job
    with pytest.raises((JobFencingConflictError, JobLeaseLostError)):
        job_repo.heartbeat("job-crash", "worker-1", fencing_token=token1)

    with pytest.raises((JobFencingConflictError, JobLeaseLostError)):
        job_repo.complete_job("job-crash", "worker-1", fencing_token=token1, state="COMPLETED")

    # Worker 2 successfully checkpoints and completes
    job_repo.save_checkpoint(
        "job-crash", "worker-2", fencing_token=claimed2.fencing_token, checkpoint_ref='{"case_1": "pass"}'
    )
    completed = job_repo.complete_job(
        "job-crash", "worker-2", fencing_token=claimed2.fencing_token, state="COMPLETED"
    )
    assert completed.state == "COMPLETED"
    assert completed.checkpoint_ref == '{"case_1": "pass"}'


def test_a03_t2_job_cancellation_and_limits(tmp_path: Path) -> None:
    """A03-T2: Cancellation request halts job before next execution; no permanent RUNNING state."""
    job_repo = InMemoryJobRepository()
    now = datetime.now(UTC)
    job = ExecutionJob(
        tenant_id="tenant-1",
        job_id="job-cancel",
        run_id="run-cancel",
        logical_key="run:tenant-1:run-cancel",
        state="QUEUED",
        created_at=now,
        updated_at=now,
    )
    job_repo.enqueue_job(job)

    # Request cancellation while QUEUED
    job_repo.request_cancellation("job-cancel")
    cancelled = job_repo.get_job("job-cancel")
    assert cancelled.cancel_requested_at is not None

    # Worker stepping honors cancellation
    eval_repo = InMemoryEvaluationRepository()
    runner = EvaluationRunner(eval_repo)
    worker = ExecutionJobWorker(job_repo, runner, worker_id="worker-canceller")
    worker.step()

    final_job = job_repo.get_job("job-cancel")
    assert final_job.state == "CANCELLED"
    assert final_job.lease_owner is None


def test_a09_t1_production_startup_fail_fast() -> None:
    """A09-T1: Production app creation must fail fast if temporary / file stores are configured."""
    settings = BackofficeSettings.from_env()
    # Configure production environment with default FILE/HEADER stores
    prod_settings = BackofficeSettings(
        host="0.0.0.0",
        port=8092,
        service_token="secret",
        auth_mode="HEADER",  # Invalid in prod
        ops_store_mode="FILE",  # Invalid in prod
        ops_store_path=settings.ops_store_path,
        ops_taxonomy_path=settings.ops_taxonomy_path,
        ops_metrics_path=settings.ops_metrics_path,
        ops_classification_rules_path=settings.ops_classification_rules_path,
        ops_audit_store_mode="FILE",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url=None,
        adapter_api_url=None,
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        eval_store_mode="FILE",
        gate_store_mode="FILE",
        fixture_store_mode="FILE",
        job_store_mode="FILE",
        environment="prod",
    )

    with pytest.raises(ValueError) as exc:
        create_app(prod_settings)
    assert "Invalid production configuration" in str(exc.value)
    assert "eval_store_mode must not be FILE in production" in str(exc.value)
    assert "gate_store_mode must not be FILE in production" in str(exc.value)


def test_migration_tool_dry_run_and_backup(tmp_path: Path) -> None:
    """Migration tool performs dry-run, backup, and count reconciliation."""
    source_file = tmp_path / "golden_evals.json"
    now = datetime.now(UTC)
    case = EvalCase(
        case_id="case-mig-1",
        tenant_id="tenant-mig",
        owner_unit_id="IT Service Desk",
        title="Migration Test",
        current_revision_id="rev-mig-1",
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    initial_state = EvaluationState(cases=(case,))
    source_file.write_text(initial_state.model_dump_json(indent=2), encoding="utf-8")

    tool = EvaluationMigrationTool()
    target_repo = InMemoryEvaluationRepository()

    # Dry-run
    dry_report = tool.migrate(source_file, target_repo, backup=True, dry_run=True)
    assert dry_report.is_dry_run is True
    assert dry_report.total_cases == 1
    assert "tenant-mig" in dry_report.tenants_found
    # In dry-run, target repository is not mutated
    assert len(target_repo.list_cases()) == 0

    # Actual migration
    report = tool.migrate(source_file, target_repo, backup=True, dry_run=False)
    assert report.is_dry_run is False
    assert report.total_cases == 1
    assert report.hash_reconciliation_passed is True
    assert report.backup_path is not None
    assert Path(report.backup_path).exists()
    assert len(target_repo.list_cases()) == 1
    assert target_repo.get_case("case-mig-1") is not None
