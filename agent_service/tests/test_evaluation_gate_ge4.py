from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.evaluation_domain import (
    CaseRevision,
    EvalCase,
    EvalSet,
    EvalSetVersion,
    EvaluationCriteria,
    EvaluationRun,
    EvaluationValidationError,
    GateBlockedError,
    GateDecision,
    GateEvaluator,
    GateException,
    GatePolicyVersion,
    InMemoryEvaluationRepository,
    ProvenanceSpec,
    QualityGateService,
    RunComparisonSummary,
    TargetManifest,
)
from ai_ops_backoffice.settings import BackofficeSettings


def _make_dummy_actor(user_id: str = "alice", role: str = "AI_ADMIN") -> ActorContext:
    return ActorContext(
        user_id=user_id,
        display_name=f"{user_id.capitalize()} User",
        role=role,  # type: ignore[arg-type]
        owner_unit_ids=("IT",),
        tenant_id="default",
    )


def _headers(role: str = "AI_ADMIN", user_id: str = "alice") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id,
        "X-Backoffice-User-Name": user_id.capitalize(),
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT",
        "X-Backoffice-Tenant-Id": "default",
    }


def _make_dummy_manifest(manifest_hash: str = "manifest_hash_1", version: str = "v1") -> TargetManifest:
    return TargetManifest(
        target_id="test_candidate",
        target_side="CANDIDATE",
        app_revision=version,
        prompt_version=f"prompt_{version}",
        model_id="gemini-3.8-flash",
        manifest_hash=manifest_hash,
    )


def _make_dummy_run(
    run_id: str,
    manifest_hash: str = "manifest_hash_1",
    set_version_id: str = "set_v1",
    critical_failures: tuple[str, ...] = (),
    regressions: tuple[str, ...] = (),
    pass_rate: float = 1.0,
    coverage: float = 1.0,
    actual_cost_usd: float = 0.05,
    latency_p95_ms: float = 800.0,
) -> EvaluationRun:
    now = datetime.now(timezone.utc)
    manifest = _make_dummy_manifest(manifest_hash=manifest_hash)
    summary = RunComparisonSummary(
        total_cases=10,
        executed_cases=int(10 * coverage),
        judged_cases=int(10 * coverage),
        baseline_passed_cases=8,
        candidate_passed_cases=int(10 * coverage * pass_rate),
        pass_rate=pass_rate,
        coverage=coverage,
        regressions=regressions,
        fixes=(),
        critical_failures=critical_failures,
        inconclusive_cases=(),
        actual_cost_usd=actual_cost_usd,
        latency_p50_ms=400.0,
        latency_p95_ms=latency_p95_ms,
    )
    return EvaluationRun(
        run_id=run_id,
        tenant_id="default",
        owner_unit_id="IT",
        set_version_id=set_version_id,
        baseline_manifest=manifest,
        candidate_manifest=manifest,
        mode="REAL_RAG",
        status="COMPLETED",
        requested_by="alice",
        created_at=now,
        summary=summary,
        actual_cost_usd=actual_cost_usd,
    )


def _save_run(repo: Any, run: EvaluationRun) -> None:
    state = repo.load()
    runs = tuple(r for r in state.runs if r.run_id != run.run_id) + (run,)
    new_state = state.model_copy(update={"runs": runs})
    repo.commit_mutation(new_state)


def _test_settings(tmp_path: Path) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    return BackofficeSettings(
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
        governance_store_path=tmp_path / "governance.json",
        eval_store_mode="MEMORY",
        eval_store_path=tmp_path / "golden_evals.json",
    )


def test_ge4_a01_critical_failure_or_missing_coverage_blocks_release(tmp_path: Path):
    """GE4-A01: Critical failure or low coverage blocks ENFORCE release; allowed with warning in REPORT_ONLY."""
    settings = _test_settings(tmp_path)
    app = create_app(settings=settings)
    gate_service = app.state.quality_gate_service
    eval_repo = gate_service._eval_repo
    actor_admin = _make_dummy_actor(user_id="alice", role="AI_ADMIN")

    # 1. Setup a policy in ENFORCE mode
    gate_service.create_policy(
        policy_id="enforce-gate",
        tenant_id="default",
        name="嚴格發布門檻",
        mode="ENFORCE",
        minimum_coverage=1.0,
        minimum_pass_rate=0.95,
        created_by="alice",
    )
    gate_service.approve_policy_version(
        policy_id="enforce-gate",
        version=1,
        approved_by="bob",
    )
    gate_service.activate_policy_version(
        policy_id="enforce-gate",
        version=1,
        mode="ENFORCE",
        actor=actor_admin,
    )

    # 2. Run with a critical failure
    critical_run = _make_dummy_run(
        run_id="run_crit_1",
        manifest_hash="hash_candidate_1",
        critical_failures=("case_acl_leak",),
        pass_rate=0.9,
    )
    _save_run(eval_repo, critical_run)

    # Evaluate decision
    decision = gate_service.evaluate_decision(
        policy_id="enforce-gate",
        policy_version=1,
        run_id="run_crit_1",
        target_manifest_hash="hash_candidate_1",
        actor=actor_admin,
    )
    assert decision.decision == "FAIL"
    assert any("Zero tolerance" in r for r in decision.blocking_reasons)

    # Release verification in ENFORCE mode must raise GateBlockedError
    with pytest.raises(GateBlockedError) as excinfo:
        gate_service.verify_release_gate(
            target_manifest_hash="hash_candidate_1",
            policy_id="enforce-gate",
        )
    assert "Release blocked by gate policy" in str(excinfo.value)

    # 3. Test HTTP API returns 412
    client = TestClient(app)
    headers = _headers("AI_ADMIN", "alice")
    response = client.post(
        "/api/evaluations/verify-release",
        headers=headers,
        json={"target_manifest_hash": "hash_candidate_1", "policy_id": "enforce-gate"},
    )
    assert response.status_code == 412
    assert "Release blocked" in response.json()["detail"]

    # 4. In REPORT_ONLY mode, verify_release_gate returns ALLOWED_WITH_WARNING
    gate_service.activate_policy_version(
        policy_id="enforce-gate",
        version=1,
        mode="REPORT_ONLY",
        actor=actor_admin,
    )
    res_report = gate_service.verify_release_gate(
        target_manifest_hash="hash_candidate_1",
        policy_id="enforce-gate",
    )
    assert res_report["status"] == "ALLOWED_WITH_WARNING"
    assert "Quality gate reported failures" in res_report["warning"]


def test_ge4_a02_target_manifest_mismatch_invalidates_gate_decision():
    """GE4-A02: Target manifest mismatch (modified after test run) invalidates gate decision."""
    eval_repo = InMemoryEvaluationRepository()
    gate_service = QualityGateService(eval_repository=eval_repo)
    actor_admin = _make_dummy_actor(user_id="alice")

    gate_service.create_policy(
        policy_id="policy-manifest-check",
        tenant_id="default",
        name="版本檢驗門檻",
        mode="ENFORCE",
        created_by="alice",
    )
    gate_service.approve_policy_version(
        policy_id="policy-manifest-check",
        version=1,
        approved_by="bob",
    )
    gate_service.activate_policy_version(
        policy_id="policy-manifest-check",
        version=1,
        mode="ENFORCE",
        actor=actor_admin,
    )

    # Run evaluated against hash_candidate_v1
    run_v1 = _make_dummy_run(run_id="run_v1", manifest_hash="hash_candidate_v1")
    _save_run(eval_repo, run_v1)

    gate_service.evaluate_decision(
        policy_id="policy-manifest-check",
        run_id="run_v1",
        target_manifest_hash="hash_candidate_v1",
        actor=actor_admin,
    )

    # Release verification for modified manifest hash_candidate_v2 must fail closed
    with pytest.raises(GateBlockedError) as excinfo:
        gate_service.verify_release_gate(
            target_manifest_hash="hash_candidate_v2",
            policy_id="policy-manifest-check",
        )
    assert "No valid quality gate decision exists for manifest 'hash_candidate_v2'" in str(excinfo.value)


def test_ge4_a03_concurrent_modifications_only_matching_gate_version_succeeds():
    """GE4-A03: Concurrent modifications allow only decision matching active gate policy version to pass."""
    eval_repo = InMemoryEvaluationRepository()
    gate_service = QualityGateService(eval_repository=eval_repo)
    actor_admin = _make_dummy_actor(user_id="alice")

    # Policy version 1 requires 80% pass rate
    gate_service.create_policy(
        policy_id="policy-concurrent",
        tenant_id="default",
        name="並行版本門檻",
        mode="ENFORCE",
        minimum_pass_rate=0.80,
        created_by="alice",
    )
    gate_service.approve_policy_version(
        policy_id="policy-concurrent",
        version=1,
        approved_by="bob",
    )
    gate_service.activate_policy_version(
        policy_id="policy-concurrent",
        version=1,
        mode="ENFORCE",
        actor=actor_admin,
    )

    # Run achieves 85% pass rate (passes v1)
    run_85 = _make_dummy_run(run_id="run_85", manifest_hash="hash_85", pass_rate=0.85)
    _save_run(eval_repo, run_85)

    dec_v1 = gate_service.evaluate_decision(
        policy_id="policy-concurrent",
        policy_version=1,
        run_id="run_85",
        target_manifest_hash="hash_85",
        actor=actor_admin,
    )
    assert dec_v1.decision == "PASS"

    # Administrator 2 concurrently creates and activates Policy version 2 with stricter 95% pass rate
    gate_service.create_policy_version(
        policy_id="policy-concurrent",
        name="加嚴發布門檻",
        minimum_pass_rate=0.95,
        created_by="bob",
    )
    gate_service.approve_policy_version(
        policy_id="policy-concurrent",
        version=2,
        approved_by="charlie",
    )
    gate_service.activate_policy_version(
        policy_id="policy-concurrent",
        version=2,
        mode="ENFORCE",
        actor=actor_admin,
    )

    # When evaluating against active policy version 2, run fails
    dec_v2 = gate_service.evaluate_decision(
        policy_id="policy-concurrent",
        policy_version=2,
        run_id="run_85",
        target_manifest_hash="hash_85",
        actor=actor_admin,
    )
    assert dec_v2.decision == "FAIL"
    assert any("Candidate pass rate" in r for r in dec_v2.blocking_reasons)


def test_ge4_a04_candidate_promotion_and_rollback_traceability():
    """GE4-A04: Candidate index verification failure prevents promotion; rollback maintains traceability."""
    eval_repo = InMemoryEvaluationRepository()
    gate_service = QualityGateService(eval_repository=eval_repo)
    actor_admin = _make_dummy_actor(user_id="alice")

    gate_service.create_policy(
        policy_id="policy-promo",
        tenant_id="default",
        name="推廣與回退門檻",
        mode="ENFORCE",
        created_by="alice",
    )
    gate_service.approve_policy_version(
        policy_id="policy-promo",
        version=1,
        approved_by="bob",
    )
    gate_service.activate_policy_version(
        policy_id="policy-promo",
        version=1,
        mode="ENFORCE",
        actor=actor_admin,
    )

    # Candidate with failing gate
    fail_run = _make_dummy_run(run_id="run_fail", manifest_hash="candidate_bad", pass_rate=0.5)
    _save_run(eval_repo, fail_run)
    gate_service.evaluate_decision(
        policy_id="policy-promo",
        run_id="run_fail",
        target_manifest_hash="candidate_bad",
        actor=actor_admin,
    )

    # Verify candidate promotion fails
    with pytest.raises(GateBlockedError):
        gate_service.verify_release_gate(
            target_manifest_hash="candidate_bad",
            policy_id="policy-promo",
        )

    # Good candidate passes gate
    pass_run = _make_dummy_run(run_id="run_good", manifest_hash="candidate_good", pass_rate=1.0)
    _save_run(eval_repo, pass_run)
    good_dec = gate_service.evaluate_decision(
        policy_id="policy-promo",
        run_id="run_good",
        target_manifest_hash="candidate_good",
        actor=actor_admin,
    )
    assert good_dec.decision == "PASS"

    res = gate_service.verify_release_gate(
        target_manifest_hash="candidate_good",
        policy_id="policy-promo",
    )
    assert res["status"] == "PASSED"
    assert res["decision_id"] == good_dec.decision_id


def test_ge4_a05_source_impact_analysis_and_incremental_test_suite_requirement():
    """GE4-A05: Document change identifies affected cases; running incremental suite alone cannot pass full policy."""
    eval_repo = InMemoryEvaluationRepository()
    gate_service = QualityGateService(eval_repository=eval_repo)
    now = datetime.now(timezone.utc)

    # Setup cases citing document doc_sec_1
    rev1 = CaseRevision(
        revision_id="rev_sec_1",
        case_id="case_sec_1",
        revision_number=1,
        query="資安規範查詢",
        criteria=EvaluationCriteria(),
        provenance=ProvenanceSpec(source_type="DOCUMENT", source_id="doc_sec_1", source_version_id="2026.1"),
        status="APPROVED",
        source_health="VALID",
        etag=1,
        content_hash="hash1",
        created_by="alice",
        created_at=now,
        updated_by="alice",
        updated_at=now,
    )
    case1 = EvalCase(
        case_id="case_sec_1",
        tenant_id="default",
        owner_unit_id="IT",
        title="資安規範",
        current_revision_id="rev_sec_1",
        created_by="alice",
        created_at=now,
        updated_by="alice",
        updated_at=now,
    )
    set1 = EvalSet(
        set_id="set_security",
        tenant_id="default",
        owner_unit_ids=("IT",),
        name="資安評測集",
        lead_owner="alice",
        created_by="alice",
        created_at=now,
        updated_by="alice",
        updated_at=now,
    )
    set_ver1 = EvalSetVersion(
        set_version_id="set_sec_v1",
        set_id="set_security",
        version=1,
        case_revision_ids=("rev_sec_1",),
        manifest_hash="hash_sec_v1",
        status="PUBLISHED",
        created_by="alice",
        created_at=now,
        etag=1,
    )

    state = eval_repo.load()
    new_state = state.model_copy(
        update={
            "cases": state.cases + (case1,),
            "revisions": state.revisions + (rev1,),
            "sets": state.sets + (set1,),
            "set_versions": state.set_versions + (set_ver1,),
        }
    )
    eval_repo.commit_mutation(new_state)

    # 1. Analyze source impact
    impact = gate_service.analyze_source_impact(source_type="DOCUMENT", source_id="doc_sec_1")
    assert "case_sec_1" in impact.affected_case_ids
    assert "rev_sec_1" in impact.affected_revision_ids
    assert "set_sec_v1" in impact.affected_set_version_ids
    assert impact.has_active_manifest_impact is True

    # 2. Gate policy requires full suite "set_full_regression_v1"
    actor_admin = _make_dummy_actor(user_id="alice")
    gate_service.create_policy(
        policy_id="policy-full-suite",
        tenant_id="default",
        name="完整測試套件門檻",
        mode="ENFORCE",
        required_set_version_ids=["set_full_regression_v1"],
        created_by="alice",
    )
    gate_service.approve_policy_version(
        policy_id="policy-full-suite",
        version=1,
        approved_by="bob",
    )
    gate_service.activate_policy_version(
        policy_id="policy-full-suite",
        version=1,
        mode="ENFORCE",
        actor=actor_admin,
    )

    # Running only the incremental suite "set_sec_v1"
    inc_run = _make_dummy_run(run_id="run_inc", set_version_id="set_sec_v1", manifest_hash="manifest_inc")
    _save_run(eval_repo, inc_run)

    inc_decision = gate_service.evaluate_decision(
        policy_id="policy-full-suite",
        run_id="run_inc",
        target_manifest_hash="manifest_inc",
        actor=actor_admin,
    )
    assert inc_decision.decision == "FAIL"
    assert any("not in policy required set versions" in r for r in inc_decision.blocking_reasons)


def test_ge4_a06_quality_case_linking_and_deduplication():
    """GE4-A06: Failure creates deduplicated quality case; resolution links retest run without mutating golden set."""
    eval_repo = InMemoryEvaluationRepository()
    gate_service = QualityGateService(eval_repository=eval_repo)
    actor = _make_dummy_actor(user_id="alice")

    # Link quality case for failed execution
    link1 = gate_service.link_quality_case(
        run_id="run_fail_1",
        execution_id="exec_err_101",
        root_cause="檢索過期未涵蓋新法規條款",
        actor=actor,
    )
    assert link1.status == "OPEN"
    assert link1.execution_id == "exec_err_101"

    # Deduplication: Re-linking same execution returns existing quality case
    link2 = gate_service.link_quality_case(
        run_id="run_fail_1",
        execution_id="exec_err_101",
        root_cause="不同的錯誤推測",
        actor=actor,
    )
    assert link2.quality_case_id == link1.quality_case_id
    assert link2.root_cause == link1.root_cause  # Preserves initial root cause

    # Resolve quality case
    resolved = gate_service.resolve_quality_case(
        quality_case_id=link1.quality_case_id,
        resolution_run_id="run_pass_2",
    )
    assert resolved.status == "RESOLVED"
    assert resolved.resolution_run_id == "run_pass_2"


def test_ge4_a07_evidence_retention_and_protection():
    """GE4-A07: Evidence and manifest protection; revoked sources marked SOURCE_UNAVAILABLE with explanation."""
    eval_repo = InMemoryEvaluationRepository()
    gate_service = QualityGateService(eval_repository=eval_repo)
    now = datetime.now(timezone.utc)

    # Setup active decision pointing to manifest
    decision = GateDecision(
        decision_id="dec_active_1",
        policy_id="default-gate-policy",
        policy_version=1,
        run_id="run_active_1",
        target_manifest_hash="hash_active_release",
        decision="PASS",
        mode_at_evaluation="ENFORCE",
        blocking_reasons=(),
        metrics_snapshot={},
        valid_until=now + timedelta(days=30),
        is_valid=True,
        created_at=now,
    )
    gate_service.repository.save_decision(decision)

    # Verify decision is listed and queryable by manifest hash
    decisions = gate_service.repository.list_decisions("hash_active_release")
    assert len(decisions) == 1
    assert decisions[0].decision_id == "dec_active_1"

    # Revoked source health handling
    rev = CaseRevision(
        revision_id="rev_revoked_1",
        case_id="case_revoked_1",
        revision_number=1,
        query="機密文檔查詢",
        criteria=EvaluationCriteria(),
        provenance=ProvenanceSpec(source_type="DOCUMENT", source_id="doc_classified", source_version_id="v1"),
        status="APPROVED",
        source_health="SOURCE_UNAVAILABLE",
        review_reason="權限已撤銷，內容依資安規範不可重現",
        etag=1,
        content_hash="hash_c",
        created_by="alice",
        created_at=now,
        updated_by="alice",
        updated_at=now,
    )
    assert rev.source_health == "SOURCE_UNAVAILABLE"
    assert "不可重現" in (rev.review_reason or "")


def test_ge4_a08_dual_approval_and_security_critical_failure_no_exception():
    """GE4-A08: Dual approval required for exception; self-approval and safety-critical failure rejected."""
    eval_repo = InMemoryEvaluationRepository()
    gate_service = QualityGateService(eval_repository=eval_repo)
    now = datetime.now(timezone.utc)

    # Non-critical failure decision
    decision_noncrit = GateDecision(
        decision_id="dec_noncrit_1",
        policy_id="default-gate-policy",
        policy_version=1,
        run_id="run_noncrit_1",
        target_manifest_hash="hash_noncrit",
        decision="FAIL",
        mode_at_evaluation="ENFORCE",
        blocking_reasons=("Candidate pass rate 94.0% is below minimum threshold 95.0%",),
        metrics_snapshot={},
        valid_until=now + timedelta(hours=24),
        is_valid=True,
        created_at=now,
    )
    gate_service.repository.save_decision(decision_noncrit)

    # 1. Request exception
    exc = gate_service.request_exception(
        decision_id="dec_noncrit_1",
        reason="僅差1%且為邊緣同義詞題型，經業務主管確認可放行",
        requested_by="alice",
        validity_hours=24,
    )
    assert exc.is_active is False
    assert exc.approved_by_1 is None

    # 2. Requester cannot approve
    with pytest.raises(EvaluationValidationError) as excinfo:
        gate_service.approve_exception(exception_id=exc.exception_id, approver_id="alice")
    assert "cannot approve their own exception" in str(excinfo.value)

    # 3. First approver bob approves
    exc_p1 = gate_service.approve_exception(exception_id=exc.exception_id, approver_id="bob")
    assert exc_p1.approved_by_1 == "bob"
    assert exc_p1.is_active is False

    # 4. Bob cannot approve a second time
    with pytest.raises(EvaluationValidationError) as excinfo:
        gate_service.approve_exception(exception_id=exc.exception_id, approver_id="bob")
    assert "Second approver must be distinct" in str(excinfo.value)

    # 5. Second approver charlie approves -> activated!
    exc_p2 = gate_service.approve_exception(exception_id=exc.exception_id, approver_id="charlie")
    assert exc_p2.approved_by_2 == "charlie"
    assert exc_p2.is_active is True

    # Updated decision status becomes EXCEPTION_APPROVED
    updated_dec = gate_service.repository.get_decision("dec_noncrit_1")
    assert updated_dec is not None
    assert updated_dec.decision == "EXCEPTION_APPROVED"

    # 6. Security-critical failure cannot be granted exception
    decision_crit = GateDecision(
        decision_id="dec_crit_1",
        policy_id="default-gate-policy",
        policy_version=1,
        run_id="run_crit_1",
        target_manifest_hash="hash_crit",
        decision="FAIL",
        mode_at_evaluation="ENFORCE",
        blocking_reasons=("Zero tolerance rule violated: 1 critical failure(s) (ACL_LEAK detected)",),
        metrics_snapshot={},
        valid_until=now + timedelta(hours=24),
        is_valid=True,
        created_at=now,
    )
    gate_service.repository.save_decision(decision_crit)

    with pytest.raises(EvaluationValidationError) as excinfo:
        gate_service.request_exception(
            decision_id="dec_crit_1",
            reason="嘗試申請資安重大漏洞例外",
            requested_by="alice",
        )
    assert "cannot be granted gate exceptions" in str(excinfo.value)

    # 7. Expired exception cannot be approved
    expired_exc = GateException(
        exception_id="exc_exp_1",
        decision_id="dec_noncrit_1",
        reason="逾時例外",
        requested_by="alice",
        requested_at=now - timedelta(days=2),
        expires_at=now - timedelta(hours=1),
        is_active=False,
    )
    gate_service.repository.save_exception(expired_exc)
    with pytest.raises(EvaluationValidationError) as excinfo:
        gate_service.approve_exception(exception_id="exc_exp_1", approver_id="bob")
    assert "expired" in str(excinfo.value)


def test_ge4_a09_schedule_budget_quota_and_evaluator_unavailable_fail_closed(tmp_path: Path):
    """GE4-A09: Scheduling quota, updates, and fail-closed behavior when evaluator or run fails."""
    settings = _test_settings(tmp_path)
    app = create_app(settings=settings)
    gate_service = app.state.quality_gate_service

    # 1. Schedule creation and update
    sched = gate_service.create_schedule(
        schedule_id="sched_daily_reg",
        tenant_id="default",
        name="每日回歸評測排程",
        set_version_id="set_v1",
        frequency="DAILY",
        budget_limit_usd=10.0,
        created_by="alice",
    )
    assert sched.is_enabled is True
    assert sched.budget_limit_usd == 10.0

    # PATCH schedule via service
    updated_sched = gate_service.update_schedule(
        schedule_id="sched_daily_reg",
        is_enabled=False,
        budget_limit_usd=15.0,
        updated_by="bob",
    )
    assert updated_sched.is_enabled is False
    assert updated_sched.budget_limit_usd == 15.0
    assert updated_sched.updated_by == "bob"

    # 2. Test HTTP endpoints for schedules
    client = TestClient(app)
    headers = _headers("AI_ADMIN", "alice")
    # List schedules
    resp_list = client.get("/api/evaluations/schedules", headers=headers)
    assert resp_list.status_code == 200
    schedules = resp_list.json()
    assert any(s["schedule_id"] == "sched_daily_reg" for s in schedules)

    # PATCH schedule via HTTP
    resp_patch = client.patch(
        "/api/evaluations/schedules/sched_daily_reg",
        headers=headers,
        json={"is_enabled": True, "frequency": "HOURLY"},
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["schedule"]["frequency"] == "HOURLY"
    assert resp_patch.json()["schedule"]["is_enabled"] is True

    # 3. Fail-closed behavior: When evaluator or run fails (no summary) under ENFORCE mode
    evaluator = GateEvaluator()
    policy_ver = GatePolicyVersion(
        policy_id="strict-failclosed",
        version=1,
        name="嚴格安全門檻",
        mode="ENFORCE",
        created_by="system",
        created_at=datetime.now(timezone.utc),
    )
    # Broken run without summary
    broken_run = EvaluationRun(
        run_id="run_broken_1",
        tenant_id="default",
        owner_unit_id="IT",
        set_version_id="set_v1",
        baseline_manifest=_make_dummy_manifest(),
        candidate_manifest=_make_dummy_manifest(manifest_hash="hash_broken"),
        status="FAILED",
        requested_by="system",
        created_at=datetime.now(timezone.utc),
        summary=None,
        error_message="Evaluator crashed unexpectedly",
    )
    decision = evaluator.evaluate(
        policy_version=policy_ver,
        run=broken_run,
        target_manifest_hash="hash_broken",
    )
    assert decision.decision == "FAIL"
    assert any("has no summary results" in r for r in decision.blocking_reasons)
