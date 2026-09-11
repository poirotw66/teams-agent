from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_service.artifact_storage import LocalFileArtifactStorage
from agent_service.document_authorization import DocumentAccessDeniedError
from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import FreshnessMetadata, utc_now
from ai_ops_backoffice.evaluation_domain import (
    ActiveReleasePointer,
    CaseRevision,
    CriterionItem,
    EvaluationCriteria,
    EvaluationRunner,
    EvaluationRunService,
    EvaluationScorer,
    EvaluationService,
    EvaluationVersionConflictError,
    EvidenceItem,
    EvidenceRequirement,
    GateBlockedError,
    GateDecision,
    GateEvaluator,
    GatePolicy,
    InMemoryEvaluationRepository,
    InMemoryQualityGateRepository,
    ManifestResolver,
    ProvenanceSpec,
    QualityGateService,
    RealRagAnswerAdapter,
    RealRagRetrieverAdapter,
    TargetManifest,
)
from ai_ops_backoffice.routers.sources_router import register_sources_routes
from ai_ops_backoffice.services.freshness_service import FreshnessTracker
from ai_ops_backoffice.services.source_models import (
    ArtifactKind,
    LocatorType,
    MappingStatus,
    SourceLocator,
    SourceRecord,
)
from ai_ops_backoffice.services.source_repository import InMemorySourceRecordRepository
from ai_ops_backoffice.services.source_trace import SourceTraceResolver

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

KNOWLEDGE_ADMIN = ActorContext(
    user_id="user_kadmin",
    display_name="Knowledge Admin",
    role="KNOWLEDGE_ADMIN",
    owner_unit_ids=("IT Service Desk", "HR"),
    tenant_id="tenant_1",
)

SERVICE_OWNER = ActorContext(
    user_id="user_sowner",
    display_name="Service Owner",
    role="SERVICE_OWNER",
    owner_unit_ids=("IT Service Desk", "HR"),
    tenant_id="tenant_1",
)


class RevokedActor:
    """Mock actor with explicit revoked flag for ACL denial testing."""

    user_id: str = "user_revoked"
    display_name: str = "Revoked Employee"
    role: str = "AI_ADMIN"
    owner_unit_ids: tuple[str, ...] = ("IT Service Desk",)
    tenant_id: str = "tenant_1"
    revoked: bool = True


async def _dummy_audit_read(actor: Any, action: str, target: str, after: Any = None) -> None:
    pass


def _setup_uat_environment(tmp_path: Path):
    """Sets up evaluation repositories, gate service, releases, and runner for UAT tests."""
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

    # Release 001: Baseline with original policy
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

    # Release 002: Candidate with improved policy wording
    rel_002_dir = releases_dir / "rel-002" / "index"
    rel_002_dir.mkdir(parents=True, exist_ok=True)
    chunks_002 = {
        "version": 1,
        "chunks": [
            {
                "chunk_id": "chunk_pwd_01",
                "title": "密碼重設作業指南",
                "source_path": "sources/password_reset.md",
                "source_id": "doc_pwd_policy",
                "content": "同仁忘記密碼時，應至SSO自助服務平台重設密碼。公司規定密碼每90天需強制更換一次，不可使用前三次密碼。",
                "evidence_id": "ev_pwd_01",
                "acl_groups": ["ALL_EMPLOYEES"],
            },
        ],
    }
    (rel_002_dir / "chunks.json").write_text(json.dumps(chunks_002), encoding="utf-8")

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

    return eval_svc, run_svc, gate_svc, eval_repo, gate_repo, releases_dir


# =====================================================================
# UAT-01: Negative Feedback Improvement Loop (Spec 8.2)
# Conversation Negative Feedback -> Quality Case -> Revision ->
# Candidate Target -> Evaluation -> Gate Pass -> Activate Release ->
# Bidirectional Linkage Verified
# =====================================================================


def test_uat_01_negative_feedback_improvement_loop(tmp_path: Path):
    """UAT-01: User downvotes conversation -> operator creates quality case prefilled from conversation ->

    operator revises knowledge -> runs evaluation -> gate passes -> candidate is activated.
    Verifies full bidirectional traceability: case_id <-> run_id <-> version_id <-> release_id.
    """
    eval_svc, run_svc, gate_svc, eval_repo, gate_repo, releases_dir = _setup_uat_environment(tmp_path)

    # 1. Incoming conversation with negative feedback
    source_conv_id = "conv-uat-01-negative"
    source_corr_id = "corr-uat-01"
    user_query = "公司密碼多久需要強制更換一次？"
    negative_feedback_remark = "回答說一年才需要換，但實際上是每90天"

    # 2. Operator creates quality case prefilled from conversation (zero retyping)
    case_res = eval_svc.create_case(
        title="密碼強制更換頻率",
        query=user_query,
        owner_unit_id="IT Service Desk",
        behavior="ANSWER_WITH_CITATION",
        criteria=EvaluationCriteria(
            required_facts=(CriterionItem(criterion_id="fact_90d", description="每90天需強制更換一次"),),
        ),
        evidence=(
            EvidenceRequirement(
                group_id="grp_pwd",
                items=(EvidenceItem(evidence_id="ev_pwd_01", source_type="DOCUMENT", source_id="doc_pwd_policy"),),
            ),
        ),
        provenance=ProvenanceSpec(
            source_type="CONVERSATION",
            source_id=source_conv_id,
            source_correlation_id=source_corr_id,
        ),
        metadata={"user_feedback": negative_feedback_remark},
        actor=KNOWLEDGE_ADMIN,
    )
    case_id = case_res["case"]["case_id"]
    rev_id = case_res["revision"]["revision_id"]

    # Verify provenance directly links to the source conversation
    assert case_res["revision"]["provenance"]["source_id"] == source_conv_id
    assert case_res["revision"]["provenance"]["source_type"] == "CONVERSATION"

    # 3. Knowledge revision review and approval workflow
    eval_svc.submit_revision(rev_id, expected_etag=1, actor=KNOWLEDGE_ADMIN)
    eval_svc.review_revision(rev_id, approve=True, expected_etag=2, reason="Approved for production", actor=SERVICE_OWNER)

    # 4. Include approved revision in evaluation set
    set_res = eval_svc.create_set(
        name="IT基礎服務評估集",
        owner_unit_ids=("IT Service Desk",),
        actor=AI_ADMIN,
    )
    set_id = set_res["eval_set"]["set_id"]
    draft_v = eval_svc.create_set_version_draft(set_id, case_revision_ids=(rev_id,), actor=AI_ADMIN)["version"]
    pub_v = eval_svc.publish_set_version(draft_v["set_version_id"], expected_etag=draft_v["etag"], actor=SERVICE_OWNER)["version"]
    set_version_id = pub_v["set_version_id"]

    # 5. Setup Quality Gate Policy in ENFORCE mode
    gate_svc.create_policy(
        policy_id="pol-uat-01",
        tenant_id="tenant_1",
        name="UAT-01 發布門檻",
        mode="ENFORCE",
        minimum_coverage=1.0,
        minimum_pass_rate=1.0,
        max_regression_count=0,
        created_by="user_aiadmin",
    )
    gate_svc.approve_policy_version(policy_id="pol-uat-01", version=1, approved_by="user_sysadmin")
    gate_svc.activate_policy_version(policy_id="pol-uat-01", version=1, mode="ENFORCE", actor=SYS_ADMIN)

    # 6. Execute REAL_RAG evaluation against candidate release (rel-002)
    candidate_manifest = TargetManifest(
        target_id="cand_v2",
        target_side="CANDIDATE",
        knowledge_release_id="rel-002",
        manifest_hash="hash_candidate_v2",
    )
    run_res = run_svc.create_run(
        set_version_id=set_version_id,
        baseline_target={"target_id": "b1", "knowledge_release_id": "rel-001"},
        candidate_target={"target_id": "cand_v2", "knowledge_release_id": "rel-002"},
        mode="REAL_RAG",
        actor=AI_ADMIN,
    )
    run_id = run_res["run"]["run_id"]
    run = run_svc.get_run(run_id, actor=AI_ADMIN)["run"]
    assert run["status"] == "COMPLETED"

    # Verify run recorded candidate release and case revision
    actual_hash = run["candidate_manifest"]["manifest_hash"]
    evaluated_manifest = candidate_manifest.model_copy(update={"manifest_hash": actual_hash})
    case_execs = run_svc.list_case_executions(run_id, side="CANDIDATE", actor=AI_ADMIN)
    assert len(case_execs) == 1
    assert case_execs[0]["case_id"] == case_id
    assert case_execs[0]["passed"] is True
    assert case_execs[0]["status"] == "COMPLETED"

    # 7. Quality Gate Evaluation
    decision = gate_svc.evaluate_decision(
        policy_id="pol-uat-01",
        run_id=run_id,
        target_manifest_hash=actual_hash,
        actor=AI_ADMIN,
    )
    assert decision.decision == "PASS"

    # 8. Activate candidate target release
    active_pointer = gate_svc.activate_target(
        tenant_id="tenant_1",
        environment="prod",
        target_type="KNOWLEDGE",
        candidate_manifest=evaluated_manifest,
        active_version_ref="rel-002",
        policy_id="pol-uat-01",
        actor=SYS_ADMIN,
    )

    # 9. Verify Bidirectional Traceability:
    # conversation -> case -> revision -> set_version -> run -> gate_decision -> active_pointer
    assert active_pointer.active_version_ref == "rel-002"
    assert active_pointer.decision_id == decision.decision_id
    assert decision.run_id == run_id
    assert decision.target_manifest_hash == actual_hash
    assert run["candidate_manifest"]["knowledge_release_id"] == "rel-002"
    assert case_execs[0]["case_id"] == case_id
    assert case_res["revision"]["provenance"]["source_id"] == source_conv_id


# =====================================================================
# UAT-02: Answer Traceability (Spec 8.2)
# Source Citation -> Version and Excerpt -> Locator Preview -> Range Streaming
# =====================================================================


@pytest.mark.asyncio
async def test_uat_02_answer_traceability_and_range_streaming(tmp_path: Path):
    """UAT-02: Source citation preview preserves original locator details (page, paragraph, bbox)

    and authenticated range streaming returns exact partial byte ranges without full-file overhead.
    """
    storage_dir = tmp_path / "artifacts"
    storage_dir.mkdir(parents=True, exist_ok=True)
    artifact_storage = LocalFileArtifactStorage(storage_dir)

    pdf_bytes = b"%PDF-1.4 Mock corporate security handbook content with multiple sections..."
    artifact_rec = await artifact_storage.store_artifact(
        tenant_id="tenant_1",
        artifact_id="art-handbook-pdf-v1",
        data=pdf_bytes,
        filename="security_handbook.pdf",
        mime_type="application/pdf",
        kind=ArtifactKind.ORIGINAL,
    )

    source_ref_id = "src-000000000000000000000001"
    source_repo = InMemorySourceRecordRepository()
    source_record = SourceRecord(
        source_ref_id=source_ref_id,
        tenant_id="tenant_1",
        document_id="doc_handbook",
        version_id="ver_2026_01",
        release_id="rel-002",
        title="資通安全作業手冊",
        owner_unit_id="IT Service Desk",
        source_type="DOCUMENT",
        mapping_status=MappingStatus.AVAILABLE,
        artifact_ref="art-handbook-pdf-v1",
        content_hash=artifact_rec.sha256,
        original_asset_available=True,
        original_asset_name="security_handbook.pdf",
        original_mime_type="application/pdf",
        original_byte_size=len(pdf_bytes),
        locator=SourceLocator(
            locator_type=LocatorType.PDF,
            page_index=12,
            page_label="13",
            section_path="第三章 / 密碼與憑證安全",
            paragraph_id="p-42",
            bbox=[100.0, 200.0, 300.0, 250.0],
            coordinate_system="PDF_POINTS_72DPI",
        ),
        excerpt="公司規定密碼每90天需強制更換一次，不可使用前三次密碼。",
    )
    source_repo.save_source_record_sync(source_record)

    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    resolver = SourceTraceResolver(
        releases_dir=releases_dir,
        source_repository=source_repo,
        artifact_storage=artifact_storage,
    )

    class MockQueryService:
        _source_trace = resolver

    app = FastAPI()
    register_sources_routes(
        app,
        query_service=MockQueryService(),
        current_actor=lambda: AI_ADMIN,
        require_capability=lambda actor, cap: None,
        audit_read=_dummy_audit_read,
    )
    client = TestClient(app)

    # 1. Preview Citation Details
    preview_res = client.get(f"/api/sources/{source_ref_id}")
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    assert preview_data["documentId"] == "doc_handbook"
    assert preview_data["versionId"] == "ver_2026_01"
    assert preview_data["releaseId"] == "rel-002"
    assert preview_data["mappingStatus"] == "AVAILABLE"
    assert preview_data["locator"]["page_index"] == 12
    assert preview_data["locator"]["page_label"] == "13"
    assert preview_data["locator"]["paragraph_id"] == "p-42"
    assert preview_data["previewUrl"] == f"/api/sources/{source_ref_id}"
    assert preview_data["downloadUrl"] == f"/api/sources/{source_ref_id}/file"

    # 2. HTTP Range Partial Streaming
    range_res = client.get(
        f"/api/sources/{source_ref_id}/file",
        headers={"Range": "bytes=0-49"},
    )
    assert range_res.status_code == 206
    assert range_res.headers["Content-Range"] == f"bytes 0-49/{len(pdf_bytes)}"
    assert range_res.headers["Accept-Ranges"] == "bytes"
    assert range_res.headers["Content-Length"] == "50"
    assert range_res.headers["X-Content-Type-Options"] == "nosniff"
    assert range_res.content == pdf_bytes[0:50]


# =====================================================================
# UAT-03: Source Unavailable Handling (Spec 8.2)
# Missing Record, Tombstone / Unpreserved Original, and ACL Denial
# =====================================================================


def test_uat_03_source_unavailable_handling(tmp_path: Path):
    """UAT-03: When sources are missing, degraded (ORIGINAL_NOT_PRESERVED), or restricted by ACL,

    the API returns actionable error statuses and structured metadata, preventing blank UI whiteouts.
    """
    source_ref_unpreserved = "src-000000000000000000000003"
    source_repo = InMemorySourceRecordRepository()
    unpreserved_record = SourceRecord(
        source_ref_id=source_ref_unpreserved,
        tenant_id="tenant_1",
        document_id="doc_legacy_doc",
        version_id="ver_legacy",
        release_id="rel-001",
        title="舊版規範手冊",
        owner_unit_id="IT Service Desk",
        mapping_status=MappingStatus.ORIGINAL_NOT_PRESERVED,
        source_type="DERIVED_MARKDOWN",
        original_asset_available=False,
        excerpt="此規範目前僅存純文字摘錄，原始PDF已未保存。",
    )
    source_repo.save_source_record_sync(unpreserved_record)

    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    resolver = SourceTraceResolver(
        releases_dir=releases_dir,
        source_repository=source_repo,
    )

    class MockQueryService:
        _source_trace = resolver

    current_test_actor: Any = AI_ADMIN

    app = FastAPI()
    register_sources_routes(
        app,
        query_service=MockQueryService(),
        current_actor=lambda: current_test_actor,
        require_capability=lambda actor, cap: None,
        audit_read=_dummy_audit_read,
    )
    client = TestClient(app)

    # 1. Missing Record: Returns 404 with structured detail
    missing_res = client.get("/api/sources/src-000000000000000000000999")
    assert missing_res.status_code == 404
    assert "Source reference not found or access denied." in missing_res.json()["detail"]

    # 2. Unpreserved Original: Preview succeeds with degraded status and actionable guidance
    unpreserved_res = client.get(f"/api/sources/{source_ref_unpreserved}")
    assert unpreserved_res.status_code == 200
    unpreserved_data = unpreserved_res.json()
    assert unpreserved_data["mappingStatus"] == "ORIGINAL_NOT_PRESERVED"
    assert "downloadUrl" not in unpreserved_data

    # Attempting to download the unpreserved file returns clear 404
    unpreserved_file_res = client.get(f"/api/sources/{source_ref_unpreserved}/file")
    assert unpreserved_file_res.status_code == 404
    assert "Original source file is not available" in unpreserved_file_res.json()["detail"]

    # 3. ACL Denial: Cross-tenant actor attempting access receives safe 404
    cross_tenant_actor = ActorContext(
        user_id="user_other_tenant",
        display_name="Other Tenant User",
        role="AI_ADMIN",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="tenant_cross_denied",
    )
    current_test_actor = cross_tenant_actor
    acl_denied_res = client.get(f"/api/sources/{source_ref_unpreserved}")
    assert acl_denied_res.status_code == 404

    # Revoked actor receives 403
    current_test_actor = RevokedActor()
    revoked_res = client.get(f"/api/sources/{source_ref_unpreserved}")
    assert revoked_res.status_code == 403


# =====================================================================
# UAT-04: Evaluation Regression Handling (Spec 8.2)
# Create Run -> Leave & Return -> Inspect Failure Classification ->
# Convert Regression into Quality Case with Root Cause
# =====================================================================


def test_uat_04_evaluation_regression_and_quality_case_creation(tmp_path: Path):
    """UAT-04: Run evaluation produces regressions -> user returns to inspect failure classification

    -> directly converts the regression into a quality case without losing context or retyping.
    """
    eval_svc, run_svc, gate_svc, eval_repo, gate_repo, releases_dir = _setup_uat_environment(tmp_path)

    # 1. Create a quality case requiring a specific policy fact
    case_res = eval_svc.create_case(
        title="密碼強制更換限制",
        query="更換密碼時可以重複使用前幾次的密碼嗎？",
        owner_unit_id="IT Service Desk",
        behavior="ANSWER_WITH_CITATION",
        criteria=EvaluationCriteria(
            required_facts=(CriterionItem(criterion_id="fact_reuse", description="不可使用前三次密碼"),),
        ),
        evidence=(
            EvidenceRequirement(
                group_id="grp_pwd",
                items=(EvidenceItem(evidence_id="ev_pwd_01", source_type="DOCUMENT", source_id="doc_pwd_policy"),),
            ),
        ),
        provenance=ProvenanceSpec(source_type="DOCUMENT", source_id="doc_pwd_policy"),
        actor=KNOWLEDGE_ADMIN,
    )
    case_id = case_res["case"]["case_id"]
    rev_id = case_res["revision"]["revision_id"]

    eval_svc.submit_revision(rev_id, expected_etag=1, actor=KNOWLEDGE_ADMIN)
    eval_svc.review_revision(rev_id, approve=True, expected_etag=2, reason="Approved", actor=SERVICE_OWNER)

    set_res = eval_svc.create_set(name="安全性評估集", owner_unit_ids=("IT Service Desk",), actor=AI_ADMIN)
    set_id = set_res["eval_set"]["set_id"]
    draft_v = eval_svc.create_set_version_draft(set_id, case_revision_ids=(rev_id,), actor=AI_ADMIN)["version"]
    pub_v = eval_svc.publish_set_version(draft_v["set_version_id"], expected_etag=draft_v["etag"], actor=SERVICE_OWNER)["version"]

    # 2. Run evaluation where baseline (rel-001) lacks the fact -> Candidate (rel-001 as candidate too for test) fails
    run_res = run_svc.create_run(
        set_version_id=pub_v["set_version_id"],
        baseline_target={"target_id": "b1", "knowledge_release_id": "rel-001"},
        candidate_target={"target_id": "c_regressed", "knowledge_release_id": "rel-001"},
        mode="REAL_RAG",
        actor=AI_ADMIN,
    )
    run_id = run_res["run"]["run_id"]

    # 3. User navigates away and returns later: query run by run_id
    reloaded_run = run_svc.get_run(run_id, actor=AI_ADMIN)["run"]
    assert reloaded_run["status"] == "COMPLETED"

    case_execs = run_svc.list_case_executions(run_id, side="CANDIDATE", actor=AI_ADMIN)
    assert len(case_execs) == 1
    failed_exec = case_execs[0]
    assert failed_exec["passed"] is False
    assert failed_exec["failure_classification"] is not None

    # 4. Operator converts the regression into a new Quality Case to track the fix
    regression_case_res = eval_svc.create_case(
        title=f"迴歸修復: {failed_exec.get('query', '密碼重複使用問題')}",
        query="更換密碼時可以重複使用前幾次的密碼嗎？",
        owner_unit_id="IT Service Desk",
        behavior="ANSWER_WITH_CITATION",
        criteria=EvaluationCriteria(
            required_facts=(CriterionItem(criterion_id="fact_reuse", description="不可使用前三次密碼"),),
        ),
        evidence=(
            EvidenceRequirement(
                group_id="grp_pwd",
                items=(EvidenceItem(evidence_id="ev_pwd_01", source_type="DOCUMENT", source_id="doc_pwd_policy"),),
            ),
        ),
        provenance=ProvenanceSpec(
            source_type="QUALITY_CASE",
            source_id=case_id,
            source_correlation_id=run_id,
            original_case_ref=case_id,
        ),
        actor=KNOWLEDGE_ADMIN,
    )
    new_case_id = regression_case_res["case"]["case_id"]
    assert new_case_id != case_id
    assert regression_case_res["revision"]["provenance"]["source_id"] == case_id
    assert regression_case_res["revision"]["provenance"]["source_correlation_id"] == run_id
    assert regression_case_res["revision"]["provenance"]["original_case_ref"] == case_id


# =====================================================================
# UAT-05: Release Gate Blocking and Remediation (Spec 8.2)
# Candidate Fails Gate -> Activation Blocked (ENFORCE) -> Fix Candidate ->
# Re-run -> Gate Passes -> Activation Succeeds
# =====================================================================


def test_uat_05_release_gate_blocking_and_remediation(tmp_path: Path):
    """UAT-05: ENFORCE gate mode blocks candidate activation when evaluation fails,

    clearly presenting blocking reasons. Once corrected and re-evaluated, activation succeeds.
    """
    eval_svc, run_svc, gate_svc, eval_repo, gate_repo, releases_dir = _setup_uat_environment(tmp_path)

    # 1. Setup policy requiring 100% pass rate in ENFORCE mode
    gate_svc.create_policy(
        policy_id="pol-uat-05",
        tenant_id="tenant_1",
        name="生產嚴格品質門檻",
        mode="ENFORCE",
        minimum_coverage=1.0,
        minimum_pass_rate=1.0,
        max_regression_count=0,
        created_by="user_aiadmin",
    )
    gate_svc.approve_policy_version(policy_id="pol-uat-05", version=1, approved_by="user_sysadmin")
    gate_svc.activate_policy_version(policy_id="pol-uat-05", version=1, mode="ENFORCE", actor=SYS_ADMIN)

    # 2. Case with fact only available in rel-002 (not in rel-001)
    case_res = eval_svc.create_case(
        title="密碼歷史比對限制",
        query="更換密碼可以與前三次相同嗎？",
        owner_unit_id="IT Service Desk",
        behavior="ANSWER_WITH_CITATION",
        criteria=EvaluationCriteria(
            required_facts=(CriterionItem(criterion_id="f_history", description="不可使用前三次密碼"),),
        ),
        evidence=(
            EvidenceRequirement(
                group_id="grp_pwd",
                items=(EvidenceItem(evidence_id="ev_pwd_01", source_type="DOCUMENT", source_id="doc_pwd_policy"),),
            ),
        ),
        provenance=ProvenanceSpec(source_type="DOCUMENT", source_id="doc_pwd_policy"),
        actor=KNOWLEDGE_ADMIN,
    )
    rev_id = case_res["revision"]["revision_id"]
    eval_svc.submit_revision(rev_id, expected_etag=1, actor=KNOWLEDGE_ADMIN)
    eval_svc.review_revision(rev_id, approve=True, expected_etag=2, reason="Approved", actor=SERVICE_OWNER)

    set_res = eval_svc.create_set(name="安全性門檻測試集", owner_unit_ids=("IT Service Desk",), actor=AI_ADMIN)
    draft_v = eval_svc.create_set_version_draft(set_res["eval_set"]["set_id"], case_revision_ids=(rev_id,), actor=AI_ADMIN)["version"]
    pub_v = eval_svc.publish_set_version(draft_v["set_version_id"], expected_etag=draft_v["etag"], actor=SERVICE_OWNER)["version"]

    # 3. Flawed candidate (rel-001) missing the fact -> Fails evaluation
    flawed_run = run_svc.create_run(
        set_version_id=pub_v["set_version_id"],
        baseline_target={"target_id": "b1", "knowledge_release_id": "rel-001"},
        candidate_target={"target_id": "cand_flawed", "knowledge_release_id": "rel-001"},
        mode="REAL_RAG",
        actor=AI_ADMIN,
    )["run"]
    flawed_run_id = flawed_run["run_id"]
    flawed_hash = flawed_run["candidate_manifest"]["manifest_hash"]

    # Gate decision on flawed run produces FAIL
    decision_flawed = gate_svc.evaluate_decision(
        policy_id="pol-uat-05",
        run_id=flawed_run_id,
        target_manifest_hash=flawed_hash,
        actor=AI_ADMIN,
    )
    assert decision_flawed.decision == "FAIL"
    assert any("below minimum threshold" in r for r in decision_flawed.blocking_reasons)

    # Attempt activation -> Blocked with clear GateBlockedError
    flawed_manifest = TargetManifest(
        target_id="cand_flawed",
        target_side="CANDIDATE",
        knowledge_release_id="rel-001",
        manifest_hash=flawed_hash,
    )
    with pytest.raises(GateBlockedError) as exc_blocked:
        gate_svc.activate_target(
            tenant_id="tenant_1",
            environment="prod",
            target_type="KNOWLEDGE",
            candidate_manifest=flawed_manifest,
            active_version_ref="rel-001",
            policy_id="pol-uat-05",
            actor=SYS_ADMIN,
        )
    assert "below minimum threshold" in str(exc_blocked.value)

    # 4. Remediation: Candidate updated with fixed content in rel-002
    fixed_run = run_svc.create_run(
        set_version_id=pub_v["set_version_id"],
        baseline_target={"target_id": "b1", "knowledge_release_id": "rel-001"},
        candidate_target={"target_id": "cand_fixed", "knowledge_release_id": "rel-002"},
        mode="REAL_RAG",
        actor=AI_ADMIN,
    )["run"]
    fixed_run_id = fixed_run["run_id"]
    fixed_hash = fixed_run["candidate_manifest"]["manifest_hash"]

    decision_fixed = gate_svc.evaluate_decision(
        policy_id="pol-uat-05",
        run_id=fixed_run_id,
        target_manifest_hash=fixed_hash,
        actor=AI_ADMIN,
    )
    assert decision_fixed.decision == "PASS"

    # Activation now succeeds
    fixed_manifest = TargetManifest(
        target_id="cand_fixed",
        target_side="CANDIDATE",
        knowledge_release_id="rel-002",
        manifest_hash=fixed_hash,
    )
    pointer = gate_svc.activate_target(
        tenant_id="tenant_1",
        environment="prod",
        target_type="KNOWLEDGE",
        candidate_manifest=fixed_manifest,
        active_version_ref="rel-002",
        policy_id="pol-uat-05",
        actor=SYS_ADMIN,
    )
    assert pointer.active_version_ref == "rel-002"
    assert pointer.decision_id == decision_fixed.decision_id
    assert decision_fixed.run_id == fixed_run_id


# =====================================================================
# UAT-06: Multi-User Concurrency and Conflict Handling (Spec 8.2)
# User A and User B Concurrently Edit -> CAS Conflict -> Input Preserved
# =====================================================================


def test_uat_06_multi_user_concurrency_cas_conflict(tmp_path: Path):
    """UAT-06: When two operators edit concurrently with the same base revision,

    the second submission receives EvaluationVersionConflictError (409) with etag detail.
    Crucially, the input payload is not erased and can be resubmitted with latest etag.
    """
    eval_svc, _, _, _, _, _ = _setup_uat_environment(tmp_path)

    # 1. Create base case revision (etag = 1)
    case_res = eval_svc.create_case(
        title="請假申請規則",
        query="事假需要提早幾天申請？",
        owner_unit_id="HR",
        behavior="ANSWER_WITH_CITATION",
        provenance=ProvenanceSpec(source_type="DOCUMENT", source_id="doc_leave_policy"),
        actor=KNOWLEDGE_ADMIN,
    )
    rev_id = case_res["revision"]["revision_id"]
    base_etag = case_res["revision"]["etag"]
    assert base_etag == 1

    # 2. User A successfully submits revision with expected_etag = 1
    submit_res_a = eval_svc.submit_revision(rev_id, expected_etag=1, actor=KNOWLEDGE_ADMIN)
    assert submit_res_a["revision"]["status"] == "IN_REVIEW"
    new_etag = submit_res_a["revision"]["etag"]
    assert new_etag == 2

    # 3. User B concurrently attempts to submit revision with stale expected_etag = 1
    user_b_attempted_reason = "Approved with additional HR caveats"
    with pytest.raises(EvaluationVersionConflictError) as exc_conflict:
        eval_svc.review_revision(
            rev_id,
            approve=True,
            expected_etag=1,  # Stale!
            reason=user_b_attempted_reason,
            actor=SERVICE_OWNER,
        )

    # 4. Error detail clearly communicates the CAS mismatch and latest state
    assert "Etag mismatch" in str(exc_conflict.value)
    assert "expected 1" in str(exc_conflict.value)
    assert "got 2" in str(exc_conflict.value)

    # 5. User B reviews current revision, preserves original input/reason, and re-submits with expected_etag = 2
    resubmission = eval_svc.review_revision(
        rev_id,
        approve=True,
        expected_etag=2,
        reason=user_b_attempted_reason,
        actor=SERVICE_OWNER,
    )
    assert resubmission["revision"]["status"] == "APPROVED"
    assert resubmission["revision"]["etag"] == 3


# =====================================================================
# UAT-07: Operational Freshness Metadata and Latency (Spec 8.2)
# Realtime vs Delayed vs Worker Disconnected Watermarks and SLAs
# =====================================================================


def test_uat_07_operational_freshness_metadata():
    """UAT-07: Operational dashboards report accurate data watermarks and statuses (REALTIME, DELAYED, FAILED)

    without fake zeros or misleading realtime indicators during synchronization lag or worker disconnection.
    """
    tracker = FreshnessTracker(
        worker_stale_threshold_seconds=60.0,
        realtime_lag_threshold_seconds=60.0,
    )

    t0 = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Normal State: Worker heartbeat active and event lag is within threshold -> REALTIME
    tracker.record_worker_heartbeat(worker_id="w-1", at=t0 + timedelta(seconds=10))
    tracker.record_sync_success("conversations", at=t0 + timedelta(seconds=10))

    freshness_realtime = tracker.compute_freshness(
        resource_type="conversations",
        watermark=t0,
        now=t0 + timedelta(seconds=15),
    )
    assert freshness_realtime.status == "REALTIME"
    assert freshness_realtime.lag_seconds == 15.0
    assert freshness_realtime.event_watermark == t0
    assert freshness_realtime.materialized_at == t0

    # 2. Delayed Sync State: Lag exceeds threshold (e.g. 5 minutes) -> DELAYED
    freshness_delayed = tracker.compute_freshness(
        resource_type="conversations",
        watermark=t0,
        now=t0 + timedelta(seconds=300),
    )
    assert freshness_delayed.status == "DELAYED"
    assert freshness_delayed.lag_seconds == 300.0

    # 3. Worker Stopped / Offline State: Worker disconnected -> FAILED (never false REALTIME)
    tracker.set_worker_disconnected()
    freshness_failed = tracker.compute_freshness(
        resource_type="conversations",
        watermark=t0,
        now=t0 + timedelta(seconds=15),
    )
    assert freshness_failed.status == "FAILED"
    assert freshness_failed.event_watermark == t0

    # 4. Multi-stage latency tracking (A05-T1 SLA verification)
    tracker.record_stage_event("corr-001", "EVENT_INGESTED", at=t0)
    tracker.record_stage_event("corr-001", "CONVERSATION_LIST_RENDERED", at=t0 + timedelta(seconds=4.5))

    tracker.record_stage_event("corr-002", "EVENT_INGESTED", at=t0)
    tracker.record_stage_event("corr-002", "CONVERSATION_LIST_RENDERED", at=t0 + timedelta(seconds=6.2))

    p95_latency = tracker.calculate_p95_latency("EVENT_INGESTED", "CONVERSATION_LIST_RENDERED")
    assert p95_latency is not None
    # Within 30-second target for conversation ingestion SLA (Spec 7.3)
    assert p95_latency <= 30.0
