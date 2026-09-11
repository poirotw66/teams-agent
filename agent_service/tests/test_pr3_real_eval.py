from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.evaluation_domain import (
    CaseRevision,
    CriterionItem,
    EvaluationCriteria,
    EvaluationNotFoundError,
    EvaluationRunner,
    EvaluationRunService,
    EvaluationScorer,
    EvaluationService,
    EvaluationValidationError,
    EvidenceItem,
    EvidenceRequirement,
    InMemoryEvaluationRepository,
    ManifestResolver,
    ProvenanceSpec,
    RealAgentSandboxAdapter,
    RealRagAnswerAdapter,
    RealRagRetrieverAdapter,
    SIDE_EFFECT_TOOLS,
    TargetExecutionInput,
    TargetManifest,
    ToolCallTrace,
    ToolConstraintsSpec,
    ToolFixture,
    ToolFixtureService,
    ToolFixtureVersion,
    TurnSpec,
)

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


def _setup_release_and_env(tmp_path: Path):
    """Sets up a test evaluation environment with pinned knowledge releases."""
    repo = InMemoryEvaluationRepository()
    svc = EvaluationService(repo, default_tenant_id="tenant_1")
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    # Setup knowledge release rel-001
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
            {
                "chunk_id": "chunk_vpn_01",
                "title": "公司VPN連線指引",
                "source_path": "sources/vpn_guide.md",
                "source_id": "doc_vpn_guide",
                "content": "遠距辦公同仁連線內網需使用GlobalProtect VPN並開啟雙因子認證。",
                "evidence_id": "ev_vpn_01",
                "acl_groups": ["ALL_EMPLOYEES"],
            },
            {
                "chunk_id": "chunk_salary_01",
                "title": "薪資核算機密辦法",
                "source_path": "sources/salary_confidential.md",
                "source_id": "doc_salary_secret",
                "content": "各級同仁薪資級距屬機密資料，僅人資薪酬主管具備存取權限。",
                "evidence_id": "ev_salary_01",
                "acl_groups": ["HR_EXEC"],
            },
        ],
    }
    (rel_001_dir / "chunks.json").write_text(json.dumps(chunks_001), encoding="utf-8")

    tool_fixture_svc = ToolFixtureService()
    resolver = ManifestResolver(repo, releases_dir=releases_dir)
    scorer = EvaluationScorer()
    runner = EvaluationRunner(
        repo,
        scorer=scorer,
        tool_fixture_service=tool_fixture_svc,
        releases_dir=releases_dir,
    )
    run_svc = EvaluationRunService(
        repository=repo,
        manifest_resolver=resolver,
        runner=runner,
        scorer=scorer,
    )
    return svc, run_svc, runner, resolver, repo, releases_dir, tool_fixture_svc


def _create_test_case(svc: EvaluationService) -> tuple[str, str]:
    """Helper to create and publish an evaluation set with a password reset case."""
    case_res = svc.create_case(
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

    svc.submit_revision(rev_id, expected_etag=1, actor=AI_ADMIN)
    svc.review_revision(rev_id, approve=True, expected_etag=2, reason="Approved for testing", actor=SYS_ADMIN)

    set_res = svc.create_set(
        name="IT基礎問答題庫",
        owner_unit_ids=("IT Service Desk",),
        actor=SYS_ADMIN,
    )
    set_id = set_res["eval_set"]["set_id"]
    draft_res = svc.create_set_version_draft(
        set_id,
        case_revision_ids=(rev_id,),
        actor=SYS_ADMIN,
    )
    draft_v = draft_res["version"]
    pub_res = svc.publish_set_version(
        draft_v["set_version_id"],
        expected_etag=draft_v["etag"],
        actor=SYS_ADMIN,
    )
    set_version_id = pub_res["version"]["set_version_id"]
    return case_id, set_version_id


# =====================================================================
# F01-T1: REAL_RAG Adapter Enforcement and Missing Adapter Rejection
# =====================================================================

def test_f01_t1_real_rag_adapter_enforcement_and_missing_adapter_rejection(tmp_path: Path):
    """F01-T1: REAL_RAG runs formal retriever and answer adapters with target manifest.
    
    When required adapters are missing, REAL_RAG is strictly rejected.
    """
    svc, run_svc, runner, resolver, repo, releases_dir, _ = _setup_release_and_env(tmp_path)
    _, set_version_id = _create_test_case(svc)

    # Subcase A: Formal adapters are present and applied with target manifest
    res = run_svc.create_run(
        set_version_id=set_version_id,
        baseline_target={
            "target_id": "baseline_v1",
            "knowledge_release_id": "rel-001",
            "retriever_config": {"top_k": 3},
        },
        candidate_target={
            "target_id": "candidate_v1",
            "knowledge_release_id": "rel-001",
            "retriever_config": {"top_k": 3},
        },
        mode="REAL_RAG",
        actor=AI_ADMIN,
    )
    run = res["run"]
    assert run["status"] == "COMPLETED"
    assert run["mode"] == "REAL_RAG"
    assert run["is_eval_eligible"] is True

    executions = run_svc.list_case_executions(run["run_id"], actor=AI_ADMIN)
    assert len(executions) == 2  # 1 baseline + 1 candidate
    for exec_item in executions:
        assert exec_item["status"] == "COMPLETED"
        assert len(exec_item["retrieved_evidence"]) > 0
        assert len(exec_item["evidence_ids"]) > 0
        assert exec_item["evidence_ids"][0] == "ev_pwd_01" or "doc_pwd_policy" in str(exec_item["retrieved_evidence"])
        assert exec_item["passed"] is True
        assert exec_item["usage_status"] in {"EXACT", "ESTIMATED"}

    # Subcase B: When runner has NO retriever adapter and NO answering adapter, REAL_RAG must be rejected
    bare_runner = EvaluationRunner(repo, scorer=EvaluationScorer())
    bare_run_svc = EvaluationRunService(
        repository=repo,
        manifest_resolver=resolver,
        runner=bare_runner,
        scorer=EvaluationScorer(),
    )

    with pytest.raises(EvaluationValidationError) as exc_info:
        bare_run_svc.create_run(
            set_version_id=set_version_id,
            baseline_target={"target_id": "b1", "knowledge_release_id": "rel-001"},
            candidate_target={"target_id": "c1", "knowledge_release_id": "rel-001"},
            mode="REAL_RAG",
            actor=AI_ADMIN,
        )
    assert "REAL_RAG mode requires registered real retriever and answer adapters" in str(exc_info.value)


# =====================================================================
# F01-T2: Candidate Retrieval Miss Causes Measurable Regression
# =====================================================================

def test_f01_t2_candidate_retrieval_miss_causes_regression_and_canary_trace(tmp_path: Path):
    """F01-T2: Deliberately cause candidate to miss evidence -> regression is detected.
    
    Canary environment verifies token usage and trace without falsely zeroing unknown costs.
    """
    svc, run_svc, _, _, repo, _, _ = _setup_release_and_env(tmp_path)
    _, set_version_id = _create_test_case(svc)

    # Baseline has access to doc_pwd_policy.
    # Candidate deliberately excludes doc_pwd_policy to simulate retrieval failure.
    res = run_svc.create_run(
        set_version_id=set_version_id,
        baseline_target={
            "target_id": "baseline_working",
            "knowledge_release_id": "rel-001",
        },
        candidate_target={
            "target_id": "candidate_degraded",
            "knowledge_release_id": "rel-001",
            "retriever_config": {"excluded_sources": ["doc_pwd_policy", "sources/password_reset.md"]},
        },
        mode="REAL_RAG",
        actor=AI_ADMIN,
    )
    run = res["run"]
    assert run["status"] == "COMPLETED"
    summary = run["summary"]

    # Candidate should fail retrieval recall while baseline passed -> regression!
    assert len(summary["regressions"]) == 1
    assert summary["baseline_passed_cases"] == 1
    assert summary["candidate_passed_cases"] == 0
    assert summary["pass_rate"] == 0.0

    # Canary inspection of candidate execution
    executions = run_svc.list_case_executions(run["run_id"], actor=AI_ADMIN)
    cand_exec = next(e for e in executions if e["target_side"] == "CANDIDATE")
    assert cand_exec["passed"] is False
    assert cand_exec["failure_classification"] in {"RETRIEVAL_MISS", "ANSWER_INCORRECT"}
    assert cand_exec["used_tokens"] > 0
    assert cand_exec["latency_ms"] > 0


# =====================================================================
# F01-T3: Target Pipeline Input Sanitization (No Golden Answer / Criteria Leak)
# =====================================================================

def test_f01_t3_target_pipeline_receives_sanitized_input_without_golden_answer_or_criteria(tmp_path: Path):
    """F01-T3: Verify input sent to target under test strictly omits expected answer, criteria, and evidence."""
    svc, _, _, _, repo, releases_dir, _ = _setup_release_and_env(tmp_path)
    _, set_version_id = _create_test_case(svc)

    captured_retriever_inputs: list[Any] = []
    captured_answering_inputs: list[Any] = []

    def spy_retriever(query: str, manifest: TargetManifest, target_input: Any) -> list[dict[str, Any]]:
        captured_retriever_inputs.append(target_input)
        return [{"chunk_id": "c1", "source_id": "doc_pwd_policy", "title": "指南", "content": "每90天更換"}]

    def spy_answering(query: str, manifest: TargetManifest, target_input: Any, retrieved: list[dict[str, Any]]) -> tuple[str, int, float]:
        captured_answering_inputs.append(target_input)
        return "每90天更換密碼 [指南]", 100, 0.00003

    spy_runner = EvaluationRunner(
        repo,
        scorer=EvaluationScorer(),
        retriever_fn=spy_retriever,
        answering_fn=spy_answering,
        releases_dir=releases_dir,
    )
    spy_run_svc = EvaluationRunService(
        repository=repo,
        manifest_resolver=ManifestResolver(repo, releases_dir=releases_dir),
        runner=spy_runner,
        scorer=EvaluationScorer(),
    )

    spy_run_svc.create_run(
        set_version_id=set_version_id,
        baseline_target={"target_id": "b_spy", "knowledge_release_id": "rel-001"},
        candidate_target={"target_id": "c_spy", "knowledge_release_id": "rel-001"},
        mode="REAL_RAG",
        actor=AI_ADMIN,
    )

    assert len(captured_retriever_inputs) > 0
    assert len(captured_answering_inputs) > 0

    for inp in captured_retriever_inputs + captured_answering_inputs:
        # Must be instance of TargetExecutionInput
        assert isinstance(inp, TargetExecutionInput)
        # Verify absence of golden answers, criteria, or evidence requirement definitions
        assert not hasattr(inp, "expected_answer")
        assert not hasattr(inp, "criteria")
        assert not hasattr(inp, "evidence")
        assert not hasattr(inp, "required_facts")
        assert not hasattr(inp, "ground_truth")
        # Verify legitimate properties are accessible
        assert hasattr(inp, "query")
        assert hasattr(inp, "conversation_history")
        assert hasattr(inp, "persona_context")


# =====================================================================
# F04-T1: Multi-Turn and Tool Scenarios (Clarification, Pronoun, Order, Args, ACL, Retry)
# =====================================================================

def test_f04_t1_multi_turn_and_tool_scenarios(tmp_path: Path):
    """F04-T1: Verifies 6 required multi-turn and tool evaluation scenarios:
    1. Clarification
    2. Multi-turn pronoun
    3. Tool ordering
    4. Invalid parameter
    5. ACL / Permission denied
    6. Tool failure and retry
    """
    svc, _, _, _, repo, releases_dir, tool_svc = _setup_release_and_env(tmp_path)

    # -------------------------------------------------------------
    # Scenario 1: Clarification turn before action
    # -------------------------------------------------------------
    clarify_rev = CaseRevision(
        revision_id="rev_sc1_clarify",
        case_id="case_sc1_clarify",
        revision_number=1,
        query="我的電腦打不開了",
        behavior="CLARIFY",
        criteria=EvaluationCriteria(
            required_facts=(CriterionItem(criterion_id="cf1", description="請問電源指示燈是否有亮"),),
        ),
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="support_sc1"),
        etag=1,
        content_hash="h1",
        created_by="admin",
        created_at=datetime.now(timezone.utc),
        updated_by="admin",
        updated_at=datetime.now(timezone.utc),
    )
    scorer = EvaluationScorer()
    m_clarify, f_clarify, pass_clarify = scorer.evaluate_execution(
        case_revision=clarify_rev,
        answer="請問電源指示燈是否有亮起？按開關是否有任何風扇運轉聲？",
        retrieved_evidence=(),
    )
    assert pass_clarify is True
    assert f_clarify is None

    # -------------------------------------------------------------
    # Scenario 2: Multi-turn pronoun reference
    # -------------------------------------------------------------
    pronoun_turns = (
        TurnSpec(
            turn_id="t1",
            user_query="請問 GlobalProtect VPN 如何設定？",
            expected_behavior="ANSWER_WITH_CITATION",
            criteria=EvaluationCriteria(
                required_facts=(CriterionItem(criterion_id="t1_c", description="下載安裝連線軟體"),),
            ),
        ),
        TurnSpec(
            turn_id="t2",
            user_query="連線它時需要雙因子認證嗎？",  # "它" refers to GlobalProtect VPN
            expected_behavior="ANSWER_WITH_CITATION",
            criteria=EvaluationCriteria(
                required_facts=(CriterionItem(criterion_id="t2_c", description="需開啟雙因子認證"),),
            ),
        ),
    )
    pronoun_rev = CaseRevision(
        revision_id="rev_sc2_pronoun",
        case_id="case_sc2_pronoun",
        revision_number=1,
        query="請問 GlobalProtect VPN 如何設定？",
        behavior="ANSWER_WITH_CITATION",
        turns=pronoun_turns,
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="support_sc2"),
        etag=1,
        content_hash="h2",
        created_by="admin",
        created_at=datetime.now(timezone.utc),
        updated_by="admin",
        updated_at=datetime.now(timezone.utc),
    )

    def multi_turn_answering(query: str, manifest: Any, target_input: Any, retrieved: Any, history: list[dict[str, str]] | None = None):
        if "它" in query:
            # Successfully resolves pronoun from conversation history
            return "連線 GlobalProtect VPN 確實需開啟雙因子認證才能登入。 [VPN連線指引]", 90, 0.00002
        return "請至入口網下載安裝連線軟體。 [VPN連線指引]", 80, 0.00002

    runner_mt = EvaluationRunner(
        repo,
        scorer=scorer,
        answering_fn=multi_turn_answering,
        releases_dir=releases_dir,
    )
    exec_pronoun = runner_mt._execute_multi_turn(
        run_id="run_mt",
        case_revision=pronoun_rev,
        manifest=TargetManifest(
            target_id="mt",
            target_side="CANDIDATE",
            manifest_hash="h",
            knowledge_release_id="rel-001",
            acl_policy="NONE",
        ),
        side="CANDIDATE",
        start_time=1.0,
    )
    assert exec_pronoun.passed is True
    assert len(exec_pronoun.trace_ref["conversation_history"]) == 4

    # -------------------------------------------------------------
    # Scenario 3: Tool ordering (query before mutation)
    # -------------------------------------------------------------
    from ai_ops_backoffice.evaluation_domain.agent_behavior_scorer import AgentBehaviorScorer
    agent_scorer = AgentBehaviorScorer()
    tc_order = ToolConstraintsSpec(
        required_tools=("query_it_ticket_status", "create_ticket"),
        tool_order=(("query_it_ticket_status", "create_ticket"),),
    )
    # Correct order
    correct_calls = (
        ToolCallTrace(call_id="c1", tool_name="query_it_ticket_status"),
        ToolCallTrace(call_id="c2", tool_name="create_ticket"),
    )
    metrics_correct = agent_scorer.score_tool_constraints(tc_order, correct_calls)
    assert all(m.pass_status == "PASS" for m in metrics_correct)

    # Inverted order -> must FAIL
    wrong_calls = (
        ToolCallTrace(call_id="c1", tool_name="create_ticket"),
        ToolCallTrace(call_id="c2", tool_name="query_it_ticket_status"),
    )
    metrics_wrong = agent_scorer.score_tool_constraints(tc_order, wrong_calls)
    order_metric = next(m for m in metrics_wrong if m.metric_id == "tool.order")
    assert order_metric.pass_status == "FAIL"

    # -------------------------------------------------------------
    # Scenario 4: Invalid tool parameter constraints
    # -------------------------------------------------------------
    tc_params = ToolConstraintsSpec(
        parameter_constraints={"query_leave_balance": {"user_id": "^E[0-9]{5}$"}},
    )
    invalid_arg_calls = (
        ToolCallTrace(call_id="c1", tool_name="query_leave_balance", arguments={"user_id": "INVALID_ID_999"}),
    )
    metrics_param = agent_scorer.score_tool_constraints(tc_params, invalid_arg_calls)
    param_metric = next(m for m in metrics_param if m.metric_id == "tool.parameter_correctness")
    assert param_metric.pass_status == "FAIL"

    # -------------------------------------------------------------
    # Scenario 5: ACL / Forbidden tools violation
    # -------------------------------------------------------------
    tc_acl = ToolConstraintsSpec(
        forbidden_tools=("admin_purge_database", "export_all_salaries"),
    )
    acl_violation_calls = (
        ToolCallTrace(call_id="c1", tool_name="query_leave_balance"),
        ToolCallTrace(call_id="c2", tool_name="admin_purge_database"),
    )
    metrics_acl = agent_scorer.score_tool_constraints(tc_acl, acl_violation_calls)
    forbidden_metric = next(m for m in metrics_acl if m.metric_id == "tool.forbidden_tools")
    assert forbidden_metric.pass_status == "FAIL"

    # -------------------------------------------------------------
    # Scenario 6: Tool failure and retry
    # -------------------------------------------------------------
    # Register a fixture that fails on attempt 1 and succeeds on attempt 2
    tool_svc.create_fixture(
        fixture_id="fix-retry-service",
        tenant_id="tenant_1",
        tool_name="sync_ad_account",
        created_by="admin",
        description="AD帳號同步工具（具備重試測試）",
        input_schema={"account": {"type": "string"}},
        mock_responses=[
            {
                "match_parameters": {"account": "user01"},
                "response_payload": {"status": "SYNCED", "account": "user01"},
                "retry_after_failures": 1,  # Fails attempt 1, succeeds attempt 2
            },
        ],
        default_response={"status": "DEFAULT_SYNC"},
    )
    tool_svc.approve_version(fixture_id="fix-retry-service", version=1, approved_by="supervisor")

    # Attempt 1: Transient failure
    call1 = tool_svc.execute_sandbox_tool(
        tool_name="sync_ad_account",
        arguments={"account": "user01"},
        attempt=1,
    )
    assert call1.is_error is True
    assert "Simulated transient failure on attempt 1" in (call1.error_message or "")

    # Attempt 2: Successful retry
    call2 = tool_svc.execute_sandbox_tool(
        tool_name="sync_ad_account",
        arguments={"account": "user01"},
        attempt=2,
    )
    assert call2.is_error is False
    assert call2.result == {"status": "SYNCED", "account": "user01"}


# =====================================================================
# F04-T2: Sandbox Intercepts Production Side Effects (No External Mutations)
# =====================================================================

def test_f04_t2_sandbox_intercepts_production_side_effects(tmp_path: Path):
    """F04-T2: Requesting sandbox to send email or create production ticket:
    - Never triggers external production mutations or emails.
    - Accurately captures interception in ToolCallTrace.
    """
    tool_svc = ToolFixtureService()

    # 1. Test side-effect tools from SIDE_EFFECT_TOOLS set
    for side_effect_name in ("send_email", "create_ticket", "dispatch_ticket"):
        trace = tool_svc.execute_sandbox_tool(
            tool_name=side_effect_name,
            arguments={"recipient": "boss@example.com", "subject": "URGENT", "body": "Fire Drill"},
        )
        assert trace.was_intercepted is True
        assert trace.side_effect_blocked is True
        assert trace.intercept_reason == "Production write/ticket/email side effects are blocked in sandbox"
        assert trace.is_error is False
        assert trace.result.get("side_effect_blocked") is True

    # 2. Test configured fixture with is_mutation=True
    tool_svc.create_fixture(
        fixture_id="fix-custom-write",
        tenant_id="tenant_1",
        tool_name="modify_employee_role",
        created_by="admin",
        description="自訂異動工具",
        input_schema={"role": {"type": "string"}},
        mock_responses=[],
        default_response={"status": "ROLE_MODIFIED"},
        is_mutation=True,
    )
    tool_svc.approve_version(fixture_id="fix-custom-write", version=1, approved_by="supervisor")

    mutation_trace = tool_svc.execute_sandbox_tool(
        tool_name="modify_employee_role",
        arguments={"role": "ADMIN"},
    )
    assert mutation_trace.was_intercepted is True
    assert mutation_trace.side_effect_blocked is True
    assert mutation_trace.intercept_reason == "Production write/ticket/email side effects are blocked in sandbox"
    assert mutation_trace.result.get("side_effect_blocked") is True
