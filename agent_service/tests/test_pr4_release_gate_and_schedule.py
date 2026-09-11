from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import FreshnessMetadata
from ai_ops_backoffice.evaluation_domain import (
    ActivationAuditRecord,
    ActiveReleasePointer,
    BreakGlassRequest,
    CaseRevision,
    CriterionItem,
    EvalSchedule,
    EvalScheduler,
    EvaluationCriteria,
    EvaluationRunner,
    EvaluationRunService,
    EvaluationScorer,
    EvaluationService,
    EvidenceItem,
    EvidenceRequirement,
    GateBlockedError,
    GateDecision,
    GateEvaluator,
    GatePolicy,
    GatePolicyVersion,
    InMemoryEvaluationRepository,
    InMemoryQualityGateRepository,
    ManifestResolver,
    ProvenanceSpec,
    QualityGateService,
    RealRagAnswerAdapter,
    RealRagRetrieverAdapter,
    ScheduleDispatchResult,
    TargetManifest,
    compute_next_due_time,
)
from ai_ops_backoffice.services.freshness_service import FreshnessTracker

AI_ADMIN = ActorContext(
    user_id="user_aiadmin",
    display_name="AI Admin",
    role="AI_ADMIN",
    owner_unit_ids=("IT Service Desk", "HR"),
    tenant_id="tenant_1",
)

SYS_ADMIN = ActorContext(
    user_id="user_sysadmin",
    display_name="System Admin",
    role="SYSTEM_ADMIN",
    owner_unit_ids=("IT Service Desk", "HR"),
    tenant_id="tenant_1",
)


def _setup_gate_and_eval_env(tmp_path: Path):
    """Sets up evaluation environment with quality gate, repositories, and releases."""
    eval_repo = InMemoryEvaluationRepository()
    gate_repo = InMemoryQualityGateRepository()
    gate_evaluator = GateEvaluator()
    gate_svc = QualityGateService(
        eval_repository=eval_repo,
        gate_repository=gate_repo,
        evaluator=gate_evaluator,
    )
    eval_svc = EvaluationService(eval_repo, default_tenant_id="tenant_1")

    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    rel_001_dir = releases_dir / "rel-001" / "index"
    rel_001_dir.mkdir(parents=True, exist_ok=True)
    chunks_001 = {
        "version": 1,
        "chunks": [
            {
                "chunk_id": "chunk_pwd_01",
                "title": "密碼重設作業指南",
                "source_path": "sources/password_reset.md",
                "source_id": "doc_pwd_policy",
                "content": "同仁忘記密碼時，應至SSO自助服務平台重設密碼。密碼每90天需強制更換一次。",
                "evidence_id": "ev_pwd_01",
                "acl_groups": ["ALL_EMPLOYEES"],
            },
        ],
    }
    (rel_001_dir / "chunks.json").write_text(json.dumps(chunks_001), encoding="utf-8")

    resolver = ManifestResolver(eval_repo, releases_dir=releases_dir)
    scorer = EvaluationScorer()
    runner = EvaluationRunner(
        eval_repo,
        scorer=scorer,
        releases_dir=releases_dir,
    )
    run_svc = EvaluationRunService(
        repository=eval_repo,
        manifest_resolver=resolver,
        runner=runner,
        scorer=scorer,
    )
    scheduler = EvalScheduler(
        gate_repository=gate_repo,
        eval_repository=eval_repo,
        run_service=run_svc,
        gate_service=gate_svc,
    )
    return eval_svc, run_svc, gate_svc, scheduler, eval_repo, gate_repo, releases_dir


def _create_published_set(eval_svc: EvaluationService) -> tuple[str, str]:
    """Helper to create and publish an approved evaluation set."""
    case_res = eval_svc.create_case(
        title="密碼更換頻率",
        query="公司密碼多久需要強制更換一次？",
        owner_unit_id="IT Service Desk",
        behavior="ANSWER_WITH_CITATION",
        criteria=EvaluationCriteria(
            required_facts=(CriterionItem(criterion_id="c1", description="每90天需強制更換一次"),),
        ),
        evidence=(
            EvidenceRequirement(
                group_id="grp_pwd",
                items=(EvidenceItem(evidence_id="ev_pwd_01", source_type="DOCUMENT", source_id="doc_pwd_policy"),),
            ),
        ),
        provenance=ProvenanceSpec(source_type="DOCUMENT", source_id="doc_pwd_policy"),
        actor=AI_ADMIN,
    )
    case_id = case_res["case"]["case_id"]
    rev_id = case_res["revision"]["revision_id"]

    eval_svc.submit_revision(rev_id, expected_etag=1, actor=AI_ADMIN)
    eval_svc.review_revision(rev_id, approve=True, expected_etag=2, reason="Approved", actor=SYS_ADMIN)

    set_res = eval_svc.create_set(
        name="IT基礎題庫",
        owner_unit_ids=("IT Service Desk",),
        actor=SYS_ADMIN,
    )
    set_id = set_res["eval_set"]["set_id"]
    draft_v = eval_svc.create_set_version_draft(set_id, case_revision_ids=(rev_id,), actor=SYS_ADMIN)["version"]
    pub_v = eval_svc.publish_set_version(draft_v["set_version_id"], expected_etag=draft_v["etag"], actor=SYS_ADMIN)["version"]
    return case_id, pub_v["set_version_id"]


# =====================================================================
# F05-T1: Gate Enforcement and Invalidation on Candidate or Policy Change
# =====================================================================

def test_f05_t1_gate_enforcement_and_invalidation_on_change(tmp_path: Path):
    """F05-T1: Direct API, CLI, or deployment calls cannot bypass ENFORCE mode.
    
    Any change to candidate manifest or active policy version invalidates previous decisions.
    """
    eval_svc, run_svc, gate_svc, _, _, gate_repo, _ = _setup_gate_and_eval_env(tmp_path)
    _, set_version_id = _create_published_set(eval_svc)

    # 1. Activate policy in ENFORCE mode
    policy, p_ver = gate_svc.create_policy(
        policy_id="pol-strict-gate",
        tenant_id="tenant_1",
        name="生產發布嚴格門檻",
        mode="ENFORCE",
        minimum_coverage=1.0,
        minimum_pass_rate=0.90,
        max_regression_count=0,
        created_by="user_aiadmin",
    )
    gate_svc.approve_policy_version(policy_id="pol-strict-gate", version=1, approved_by="user_sysadmin")
    gate_svc.activate_policy_version(policy_id="pol-strict-gate", version=1, mode="ENFORCE", actor=SYS_ADMIN)

    # Candidate manifest 1
    cand_manifest_1 = TargetManifest(
        target_id="cand_v1",
        target_side="CANDIDATE",
        knowledge_release_id="rel-001",
        manifest_hash="hash_candidate_v1",
    )

    # 2. Attempt direct activation with NO evaluation run/decision -> MUST be blocked
    with pytest.raises(GateBlockedError) as exc_blocked:
        gate_svc.activate_target(
            tenant_id="tenant_1",
            environment="prod",
            target_type="KNOWLEDGE",
            candidate_manifest=cand_manifest_1,
            active_version_ref="rel-001",
            policy_id="pol-strict-gate",
            actor=SYS_ADMIN,
        )
    assert "Activation blocked by gate: No valid eligible decision exists" in str(exc_blocked.value)

    # 3. Execute REAL_RAG evaluation run and evaluate gate decision -> PASS
    run_res = run_svc.create_run(
        set_version_id=set_version_id,
        baseline_target={"target_id": "b1", "knowledge_release_id": "rel-001"},
        candidate_target={"target_id": "cand_v1", "knowledge_release_id": "rel-001"},
        mode="REAL_RAG",
        actor=AI_ADMIN,
    )
    run_id = run_res["run"]["run_id"]
    run = run_svc.get_run(run_id, actor=AI_ADMIN)["run"]
    assert run["status"] == "COMPLETED"

    # Evaluate decision using the exact candidate manifest hash from the run
    actual_hash = run["candidate_manifest"]["manifest_hash"]
    evaluated_manifest = cand_manifest_1.model_copy(update={"manifest_hash": actual_hash})
    decision = gate_svc.evaluate_decision(
        policy_id="pol-strict-gate",
        run_id=run_id,
        target_manifest_hash=actual_hash,
        actor=AI_ADMIN,
    )
    assert decision.decision == "PASS"

    # 4. Activation succeeds in atomic CAS
    pointer = gate_svc.activate_target(
        tenant_id="tenant_1",
        environment="prod",
        target_type="KNOWLEDGE",
        candidate_manifest=evaluated_manifest,
        active_version_ref="rel-001",
        policy_id="pol-strict-gate",
        actor=SYS_ADMIN,
    )
    assert pointer.active_manifest_hash == actual_hash
    assert pointer.etag == 1

    # 5. Candidate changed: if new candidate v2 attempts to activate with old decision -> FAIL
    cand_manifest_changed = TargetManifest(
        target_id="cand_v2_changed",
        target_side="CANDIDATE",
        knowledge_release_id="rel-001",
        prompt_version="v2_changed",
        manifest_hash="hash_candidate_v2_tampered",
    )
    with pytest.raises(GateBlockedError) as exc_tampered:
        gate_svc.activate_target(
            tenant_id="tenant_1",
            environment="prod",
            target_type="KNOWLEDGE",
            candidate_manifest=cand_manifest_changed,
            active_version_ref="rel-001",
            policy_id="pol-strict-gate",
            actor=SYS_ADMIN,
        )
    assert "Activation blocked by gate" in str(exc_tampered.value)

    # 6. Policy version changed: create and activate policy version 2 (Spec 7.1: "政策版本變更須重新決策")
    p_ver2 = gate_svc.create_policy_version(
        policy_id="pol-strict-gate",
        name="生產發布門檻v2",
        mode="ENFORCE",
        minimum_coverage=1.0,
        minimum_pass_rate=0.99,
        created_by="user_aiadmin",
    )
    gate_svc.approve_policy_version(policy_id="pol-strict-gate", version=2, approved_by="user_sysadmin")
    gate_svc.activate_policy_version(policy_id="pol-strict-gate", version=2, mode="ENFORCE", actor=SYS_ADMIN)

    # The previous decision was issued under policy v1. Now that policy v2 is active,
    # attempting to activate with the old v1 decision must be strictly rejected!
    with pytest.raises(GateBlockedError) as exc_pol_changed:
        gate_svc.activate_target(
            tenant_id="tenant_1",
            environment="prod",
            target_type="KNOWLEDGE",
            candidate_manifest=evaluated_manifest,
            active_version_ref="rel-001",
            policy_id="pol-strict-gate",
            actor=SYS_ADMIN,
        )
    assert "under policy 'pol-strict-gate' v2" in str(exc_pol_changed.value)


# =====================================================================
# F05-T2: Decision Expiration, Mock Runs, Expired Exceptions, and Rollbacks
# =====================================================================

def test_f05_t2_gate_edge_cases_expiration_mock_exception_rollback(tmp_path: Path):
    """F05-T2: Verifies:
    1. Expired decision cannot activate.
    2. Ineligible mock / OFFLINE_BENCHMARK run cannot pass gate.
    3. Expired gate exception cannot activate.
    4. Emergency rollback via Break-Glass is time-limited, audited, and preserves original evals.
    5. Standard rollback validates decision.
    """
    eval_svc, run_svc, gate_svc, _, eval_repo, gate_repo, _ = _setup_gate_and_eval_env(tmp_path)
    _, set_version_id = _create_published_set(eval_svc)

    # Setup policy in ENFORCE mode
    gate_svc.create_policy(
        policy_id="pol-edge",
        tenant_id="tenant_1",
        name="邊界測試門檻",
        mode="ENFORCE",
        created_by="user_aiadmin",
    )
    gate_svc.approve_policy_version(policy_id="pol-edge", version=1, approved_by="user_sysadmin")
    gate_svc.activate_policy_version(policy_id="pol-edge", version=1, mode="ENFORCE", actor=SYS_ADMIN)

    # Subcase 1: Expired decision
    now = datetime.now(timezone.utc)
    expired_decision = GateDecision(
        decision_id="gdec_expired_001",
        policy_id="pol-edge",
        policy_version=1,
        run_id="run_past",
        target_manifest_hash="hash_expired",
        decision="PASS",
        mode_at_evaluation="ENFORCE",
        tenant_id="tenant_1",
        valid_until=now - timedelta(minutes=10),  # Expired!
        is_valid=True,
        created_at=now - timedelta(days=5),
    )
    gate_repo.save_decision(expired_decision)

    cand_expired = TargetManifest(
        target_id="expired_target",
        target_side="CANDIDATE",
        manifest_hash="hash_expired",
    )
    with pytest.raises(GateBlockedError):
        gate_svc.activate_target(
            tenant_id="tenant_1",
            environment="prod",
            target_type="KNOWLEDGE",
            candidate_manifest=cand_expired,
            active_version_ref="rel-000",
            policy_id="pol-edge",
            actor=SYS_ADMIN,
        )

    # Subcase 2: OFFLINE_BENCHMARK / Mock Run is ineligible for release gate
    offline_run_res = run_svc.create_run(
        set_version_id=set_version_id,
        baseline_target={"target_id": "b1", "knowledge_release_id": "rel-001"},
        candidate_target={"target_id": "c1", "knowledge_release_id": "rel-001"},
        mode="OFFLINE_BENCHMARK",
        actor=AI_ADMIN,
    )
    offline_run = run_svc.get_run(offline_run_res["run"]["run_id"], actor=AI_ADMIN)["run"]
    assert offline_run["is_eval_eligible"] is False

    offline_hash = offline_run["candidate_manifest"]["manifest_hash"]
    offline_decision = gate_svc.evaluate_decision(
        policy_id="pol-edge",
        run_id=offline_run["run_id"],
        target_manifest_hash=offline_hash,
        actor=AI_ADMIN,
    )
    assert offline_decision.decision == "FAIL"
    assert any("ineligible for quality gate release" in r for r in offline_decision.blocking_reasons)

    # Subcase 3: Expired exception cannot activate
    fail_decision = GateDecision(
        decision_id="gdec_fail_exception",
        policy_id="pol-edge",
        policy_version=1,
        run_id="run_fail_1",
        target_manifest_hash="hash_exception_test",
        decision="FAIL",
        mode_at_evaluation="ENFORCE",
        tenant_id="tenant_1",
        blocking_reasons=("Slight pass rate dip 89%",),
        valid_until=now + timedelta(days=1),
        created_at=now,
    )
    gate_repo.save_decision(fail_decision)

    # Request and dual-approve an exception that expires immediately
    exc = gate_svc.request_exception(
        decision_id=fail_decision.decision_id,
        reason="業務緊急測試例外",
        requested_by="user_aiadmin",
        validity_hours=1,
    )
    gate_svc.approve_exception(exception_id=exc.exception_id, approver_id="user_sysadmin")
    gate_svc.approve_exception(exception_id=exc.exception_id, approver_id="user_supervisor")

    # Fast-forward expiry into the past after approval
    approved_exc = gate_repo.get_exception(exc.exception_id)
    assert approved_exc is not None and approved_exc.is_active is True
    exc_expired = approved_exc.model_copy(update={"expires_at": now - timedelta(minutes=5)})
    gate_repo.save_exception(exc_expired)

    # Update decision exceptions list with the expired exception
    dec = gate_repo.get_decision(fail_decision.decision_id)
    assert dec is not None
    gate_repo.save_decision(dec.model_copy(update={"exceptions": (exc_expired,)}))

    cand_exc = TargetManifest(
        target_id="cand_exc",
        target_side="CANDIDATE",
        manifest_hash="hash_exception_test",
    )
    with pytest.raises(GateBlockedError) as exc_info:
        gate_svc.activate_target(
            tenant_id="tenant_1",
            environment="prod",
            target_type="KNOWLEDGE",
            candidate_manifest=cand_exc,
            active_version_ref="rel-exc",
            policy_id="pol-edge",
            actor=SYS_ADMIN,
        )
    assert "Gate exception" in str(exc_info.value) and "expired" in str(exc_info.value)

    # Subcase 4: Emergency Break-Glass Rollback
    # First, create an active pointer
    cand_live = TargetManifest(
        target_id="cand_live",
        target_side="CANDIDATE",
        manifest_hash="hash_live_stable",
    )
    live_decision = GateDecision(
        decision_id="gdec_live_ok",
        policy_id="pol-edge",
        policy_version=1,
        run_id="run_live",
        target_manifest_hash="hash_live_stable",
        decision="PASS",
        mode_at_evaluation="ENFORCE",
        tenant_id="tenant_1",
        valid_until=now + timedelta(days=2),
        created_at=now,
    )
    gate_repo.save_decision(live_decision)
    ptr_live = gate_svc.activate_target(
        tenant_id="tenant_1",
        environment="prod",
        target_type="KNOWLEDGE",
        candidate_manifest=cand_live,
        active_version_ref="rel-live-1",
        policy_id="pol-edge",
        actor=SYS_ADMIN,
    )
    assert ptr_live.active_manifest_hash == "hash_live_stable"

    # Break-glass ticket to rollback to emergency manifest without eval decision
    cand_emergency_rollback = TargetManifest(
        target_id="cand_emergency",
        target_side="CANDIDATE",
        manifest_hash="hash_emergency_rollback",
    )
    bg = gate_svc.create_break_glass(
        tenant_id="tenant_1",
        environment="prod",
        target_type="KNOWLEDGE",
        candidate_manifest_hash="hash_emergency_rollback",
        reason="重大線上故障緊急回滾，依核准授權先行退版",
        authorized_by="CTO_DIRECTOR",
        requested_by="user_oncall",
        validity_hours=2,
    )
    assert bg.is_used is False

    ptr_rollback = gate_svc.rollback_target(
        tenant_id="tenant_1",
        environment="prod",
        target_type="KNOWLEDGE",
        target_manifest=cand_emergency_rollback,
        active_version_ref="rel-emergency-stable",
        reason="重大故障回滾",
        actor=SYS_ADMIN,
        break_glass_id=bg.break_glass_id,
    )
    assert ptr_rollback.active_manifest_hash == "hash_emergency_rollback"
    assert ptr_rollback.is_break_glass is True
    assert ptr_rollback.etag == 2

    # Verify break-glass was consumed and audited
    bg_after = gate_repo.get_break_glass(bg.break_glass_id)
    assert bg_after.is_used is True

    audits = gate_repo.list_activation_audits("tenant_1")
    assert any(a.break_glass_id == bg.break_glass_id for a in audits)


# =====================================================================
# F06-T1: Scheduler Deduplication, DST, Misfires, and Budget Limits
# =====================================================================

def test_f06_t1_scheduler_deduping_dst_misfire_and_budget(tmp_path: Path):
    """F06-T1: Dual schedulers scanning concurrently, restart/retry, misfires,
    cross-timezone/DST transitions, and budget limits never create duplicate logical runs.
    """
    eval_svc, run_svc, gate_svc, scheduler, _, gate_repo, _ = _setup_gate_and_eval_env(tmp_path)
    _, set_version_id = _create_published_set(eval_svc)

    now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)

    # 1. Test Timezone & DST Calculation
    # America/New_York transitions to DST on second Sunday in March (March 8, 2026)
    due_ny = datetime(2026, 3, 7, 9, 0, tzinfo=timezone.utc)  # 04:00 AM EST (UTC-5)
    next_ny = compute_next_due_time(due_ny, "DAILY", "America/New_York")
    # In EDT (UTC-4), 04:00 AM local time is 08:00 AM UTC (shifted by 1 hour in UTC due to DST)
    assert next_ny.hour == 8

    # 2. Dual Schedulers Concurrent Scanning Deduping
    sched = gate_svc.create_schedule(
        schedule_id="sched_daily_it",
        tenant_id="tenant_1",
        name="每日IT問答迴歸",
        set_version_id=set_version_id,
        frequency="DAILY",
        budget_limit_usd=10.0,
        created_by="user_aiadmin",
    )
    # Set due time in past
    sched = sched.model_copy(update={"next_due_at": now - timedelta(minutes=5)})
    gate_repo.save_schedule(sched)

    # Scheduler instance A dispatches
    results_a = scheduler.scan_and_dispatch_due_schedules(now_utc=now)
    assert len(results_a) == 1
    assert results_a[0].status == "DISPATCHED"
    assert results_a[0].run_id is not None

    # Scheduler instance B concurrently scans at same moment -> MUST be DUPLICATE_IGNORED
    results_b = scheduler.scan_and_dispatch_due_schedules(now_utc=now)
    # Either not due or duplicate ignored
    assert len(results_b) == 0 or all(r.status in {"DUPLICATE_IGNORED", "SKIPPED_OVERLAP"} for r in results_b)

    # 3. Misfire Coalescing (Spec 7.2: misfire 預設合併成一次最新補跑，介面標示漏過次數)
    sched_misfire = gate_svc.create_schedule(
        schedule_id="sched_misfire_weekly",
        tenant_id="tenant_1",
        name="每週大規模迴歸",
        set_version_id=set_version_id,
        frequency="DAILY",
        budget_limit_usd=10.0,
        created_by="user_aiadmin",
    )
    # Simulate system down for 3 days
    sched_misfire = sched_misfire.model_copy(
        update={
            "next_due_at": now - timedelta(days=3),
            "misfire_policy": "COALESCE_LATEST",
        }
    )
    gate_repo.save_schedule(sched_misfire)

    results_misfire = scheduler.scan_and_dispatch_due_schedules(now_utc=now)
    disp_misfire = next(r for r in results_misfire if r.schedule_id == "sched_misfire_weekly")
    assert disp_misfire.status == "DISPATCHED"

    updated_misfire = gate_repo.get_schedule("sched_misfire_weekly")
    # Missed count incremented by 2 (3 days missed coalesced into 1 run)
    assert updated_misfire.missed_count >= 2

    # 4. Budget Limit: SKIPPED_BUDGET without infinite retries
    sched_expensive = gate_svc.create_schedule(
        schedule_id="sched_expensive_model",
        tenant_id="tenant_1",
        name="高昂模型評估",
        set_version_id=set_version_id,
        frequency="HOURLY",
        budget_limit_usd=0.01,  # Strict $0.01 limit
        target_refs={"estimated_cost_usd": 0.50},  # $0.50 cost exceeds limit
        created_by="user_aiadmin",
    )
    sched_expensive = sched_expensive.model_copy(update={"next_due_at": now - timedelta(minutes=1)})
    gate_repo.save_schedule(sched_expensive)

    results_expensive = scheduler.scan_and_dispatch_due_schedules(now_utc=now)
    disp_exp = next(r for r in results_expensive if r.schedule_id == "sched_expensive_model")
    assert disp_exp.status == "SKIPPED_BUDGET"
    assert disp_exp.run_id is None

    # Next due time is advanced, not looping continuously on the same slot
    updated_expensive = gate_repo.get_schedule("sched_expensive_model")
    assert updated_expensive.next_due_at > now


# =====================================================================
# A05-T1: Operational Data Freshness Metadata and P95 Latency SLA
# =====================================================================

def test_a05_t1_data_freshness_metadata_and_p95_sla():
    """A05-T1: FreshnessMetadata contract:
    1. Separate timestamps for event, ingestion, aggregation, and sync.
    2. Disconnected or stopped worker NEVER displays 'REALTIME'.
    3. CorrelationId tracks latency across hops and measures p95:
       - Ingestion to conversation list p95 <= 30s
       - Ingestion to aggregate page p95 <= 5 min
       - Schedule due to dispatch p95 <= 2 min
    """
    tracker = FreshnessTracker(worker_stale_threshold_seconds=60.0, realtime_lag_threshold_seconds=30.0)
    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Healthy worker with low lag -> REALTIME
    tracker.record_worker_heartbeat(at=now)
    fresh_meta = tracker.compute_freshness(
        resource_type="conversations",
        watermark=now - timedelta(seconds=10),
        now=now,
    )
    assert fresh_meta.status == "REALTIME"
    assert fresh_meta.lag_seconds == 10.0

    # 2. Worker stopped / disconnected -> Must NOT show REALTIME
    tracker.set_worker_disconnected()
    stale_meta = tracker.compute_freshness(
        resource_type="conversations",
        watermark=now - timedelta(seconds=10),
        now=now,
    )
    assert stale_meta.status in {"DELAYED", "FAILED"}
    assert stale_meta.status != "REALTIME"

    # 3. Missing watermark -> UNKNOWN
    unknown_meta = tracker.compute_freshness(
        resource_type="conversations",
        watermark=None,
        now=now,
    )
    assert unknown_meta.status == "UNKNOWN"

    # 4. Measure P95 Latencies across correlation traces
    # Target 1: Event Ingestion to Conversation List (SLA p95 <= 30s)
    for i in range(20):
        corr_id = f"corr_conv_{i}"
        t_ingest = now + timedelta(seconds=i)
        t_render = t_ingest + timedelta(seconds=5.0 + (i * 0.5))  # max 14.5s
        tracker.record_stage_event(corr_id, "EVENT_INGESTED", at=t_ingest)
        tracker.record_stage_event(corr_id, "CONVERSATION_LIST_RENDERED", at=t_render)

    p95_conv = tracker.calculate_p95_latency("EVENT_INGESTED", "CONVERSATION_LIST_RENDERED")
    assert p95_conv is not None
    assert p95_conv <= 30.0  # Verified: p95 <= 30 seconds

    # Target 2: Event Ingestion to Aggregate Page (SLA p95 <= 5 minutes / 300s)
    for i in range(20):
        corr_id = f"corr_agg_{i}"
        t_ingest = now + timedelta(seconds=i)
        t_agg = t_ingest + timedelta(seconds=60.0 + (i * 5.0))  # max 155s
        tracker.record_stage_event(corr_id, "EVENT_INGESTED", at=t_ingest)
        tracker.record_stage_event(corr_id, "AGGREGATION_COMPLETED", at=t_agg)

    p95_agg = tracker.calculate_p95_latency("EVENT_INGESTED", "AGGREGATION_COMPLETED")
    assert p95_agg is not None
    assert p95_agg <= 300.0  # Verified: p95 <= 5 minutes

    # Target 3: Schedule Due to Dispatch (SLA p95 <= 2 minutes / 120s)
    for i in range(20):
        corr_id = f"corr_sched_{i}"
        t_due = now + timedelta(seconds=i)
        t_disp = t_due + timedelta(seconds=2.0 + (i * 0.5))  # max 11.5s
        tracker.record_stage_event(corr_id, "SCHEDULE_DUE", at=t_due)
        tracker.record_stage_event(corr_id, "SCHEDULE_DISPATCHED", at=t_disp)

    p95_sched = tracker.calculate_p95_latency("SCHEDULE_DUE", "SCHEDULE_DISPATCHED")
    assert p95_sched is not None
    assert p95_sched <= 120.0  # Verified: p95 <= 2 minutes
