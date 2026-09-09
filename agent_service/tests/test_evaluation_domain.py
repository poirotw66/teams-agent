from __future__ import annotations

import pytest

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.evaluation_domain import (
    CandidateGenerationManager,
    CriterionItem,
    EvaluationAuthorizationError,
    EvaluationCriteria,
    EvaluationImportExportManager,
    EvaluationNotFoundError,
    EvaluationService,
    EvaluationValidationError,
    EvaluationVersionConflictError,
    EvidenceItem,
    EvidenceRequirement,
    InMemoryEvaluationRepository,
    ProvenanceSpec,
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

AUDITOR = ActorContext(
    user_id="user_auditor",
    display_name="Auditor",
    role="AUDITOR",
    owner_unit_ids=("IT Service Desk",),
    tenant_id="tenant_1",
)

OTHER_UNIT_ADMIN = ActorContext(
    user_id="user_other",
    display_name="Finance Admin",
    role="KNOWLEDGE_ADMIN",
    owner_unit_ids=("Finance",),
    tenant_id="tenant_1",
)


SYSTEM_ADMIN = ActorContext(
    user_id="user_sysadmin",
    display_name="System Admin",
    role="SYSTEM_ADMIN",
    owner_unit_ids=("IT Service Desk", "HR"),
    tenant_id="tenant_1",
)

OTHER_SERVICE_OWNER = ActorContext(
    user_id="user_sowner_2",
    display_name="Service Owner 2",
    role="SERVICE_OWNER",
    owner_unit_ids=("IT Service Desk", "HR"),
    tenant_id="tenant_1",
)


def _setup_service() -> tuple[EvaluationService, EvaluationImportExportManager, CandidateGenerationManager]:
    repo = InMemoryEvaluationRepository()
    svc = EvaluationService(repo, default_tenant_id="tenant_1")
    iem = EvaluationImportExportManager(svc)
    cgm = CandidateGenerationManager(svc)
    return svc, iem, cgm


def test_ge1_a01_candidate_creation_and_unapproved_publish_blocked():
    """GE1-A01: Unapproved cases cannot be published into an eval set version."""
    svc, _, _ = _setup_service()

    # Create case
    created = svc.create_case(
        title="請假規定",
        query="如何申請特休？",
        owner_unit_id="HR",
        behavior="ANSWER_WITH_CITATION",
        criteria=EvaluationCriteria(
            required_facts=(CriterionItem(criterion_id="c1", description="需於前三天提出申請"),),
            reference_answer="請至差勤系統填寫特休假單並於三日前送出。",
        ),
        evidence=(
            EvidenceRequirement(
                group_id="g1",
                items=(EvidenceItem(evidence_id="e1", source_type="DOCUMENT", source_id="doc_hr_01"),),
            ),
        ),
        provenance=ProvenanceSpec(source_type="DOCUMENT", source_id="doc_hr_01", source_version_id="v1"),
        actor=KNOWLEDGE_ADMIN,
    )
    rev_id = created["revision"]["revision_id"]
    assert created["revision"]["status"] == "DRAFT"

    # Create eval set
    eval_set = svc.create_set(
        name="HR 基準題庫",
        owner_unit_ids=("HR",),
        purpose="DEVELOPMENT",
        actor=KNOWLEDGE_ADMIN,
    )["eval_set"]
    set_id = eval_set["set_id"]

    # Draft set version
    draft_ver = svc.create_set_version_draft(
        set_id,
        case_revision_ids=(rev_id,),
        actor=KNOWLEDGE_ADMIN,
    )["version"]
    assert draft_ver["status"] == "DRAFT"

    # Attempt to publish unapproved revision -> must be blocked
    with pytest.raises(EvaluationValidationError, match="only APPROVED revisions can be published"):
        svc.publish_set_version(
            draft_ver["set_version_id"],
            expected_etag=draft_ver["etag"],
            actor=SERVICE_OWNER,
        )


def test_ge1_a02_revision_immutability_and_manifest_hash():
    """GE1-A02: Modifying case requires a new revision; published version keeps original hash and members."""
    svc, _, _ = _setup_service()

    # Create case and submit for review
    created = svc.create_case(
        title="系統帳號解鎖",
        query="帳號被鎖定如何處理？",
        owner_unit_id="IT Service Desk",
        behavior="ANSWER_WITH_CITATION",
        provenance=ProvenanceSpec(source_type="FAQ", source_id="faq_it_01"),
        actor=KNOWLEDGE_ADMIN,
    )
    case_id = created["case"]["case_id"]
    rev1 = created["revision"]

    svc.submit_revision(rev1["revision_id"], expected_etag=rev1["etag"], actor=KNOWLEDGE_ADMIN)
    approved_rev1 = svc.review_revision(
        rev1["revision_id"],
        approve=True,
        reason="Verified against IT policy",
        expected_etag=rev1["etag"] + 1,
        actor=SERVICE_OWNER,
    )["revision"]
    assert approved_rev1["status"] == "APPROVED"

    # Publish set v1
    eval_set = svc.create_set(
        name="IT 標準題庫",
        owner_unit_ids=("IT Service Desk",),
        purpose="DEVELOPMENT",
        actor=KNOWLEDGE_ADMIN,
    )["eval_set"]
    draft_v1 = svc.create_set_version_draft(
        eval_set["set_id"],
        case_revision_ids=(approved_rev1["revision_id"],),
        actor=KNOWLEDGE_ADMIN,
    )["version"]
    pub_v1 = svc.publish_set_version(
        draft_v1["set_version_id"],
        expected_etag=draft_v1["etag"],
        actor=SERVICE_OWNER,
    )["version"]

    v1_hash = pub_v1["manifest_hash"]
    assert v1_hash
    assert pub_v1["status"] == "PUBLISHED"

    # Modify case -> creates revision 2
    rev2 = svc.create_revision(
        case_id,
        query="帳號被鎖定要找誰解鎖？需要主管核准嗎？",
        actor=KNOWLEDGE_ADMIN,
    )["revision"]
    assert rev2["revision_number"] == 2
    assert rev2["status"] == "DRAFT"

    # Check that published v1 is unchanged
    set_detail = svc.get_set_detail(eval_set["set_id"], actor=KNOWLEDGE_ADMIN)
    published_in_store = next(v for v in set_detail["versions"] if v["set_version_id"] == pub_v1["set_version_id"])
    assert published_in_store["manifest_hash"] == v1_hash
    assert published_in_store["case_revision_ids"] == [approved_rev1["revision_id"]]


def test_ge1_a03_separation_of_duties_enforced():
    """GE1-A03: Authors cannot approve their own revisions; other reviewer can approve."""
    svc, _, _ = _setup_service()

    # SYSTEM_ADMIN has both write and review capabilities
    created = svc.create_case(
        title="差旅費報銷標準",
        query="出差計程車費可否報銷？",
        owner_unit_id="IT Service Desk",
        behavior="ANSWER_WITH_CITATION",
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="manual:01"),
        actor=SYSTEM_ADMIN,
    )
    rev = created["revision"]
    svc.submit_revision(rev["revision_id"], expected_etag=rev["etag"], actor=SYSTEM_ADMIN)

    # Author tries to self-approve -> must fail with separation of duties error
    with pytest.raises(EvaluationAuthorizationError, match="Authors cannot approve their own revisions"):
        svc.review_revision(
            rev["revision_id"],
            approve=True,
            reason="I approve my own work",
            expected_etag=rev["etag"] + 1,
            actor=SYSTEM_ADMIN,
        )

    # Authorized independent reviewer approves -> success
    reviewed = svc.review_revision(
        rev["revision_id"],
        approve=True,
        reason="Approved by independent service owner",
        expected_etag=rev["etag"] + 1,
        actor=SERVICE_OWNER,
    )["revision"]
    assert reviewed["status"] == "APPROVED"
    assert reviewed["reviewed_by"] == SERVICE_OWNER.user_id


def test_ge1_a04_holdout_and_scope_isolation():
    """GE1-A04: Holdout set is inaccessible without ops.evals.holdout.read; cross-unit is blocked."""
    svc, _, _ = _setup_service()

    # Create HOLDOUT set by SYSTEM_ADMIN (who has holdout.read and write)
    holdout_set = svc.create_set(
        name="機密保留驗收題庫",
        owner_unit_ids=("IT Service Desk",),
        purpose="HOLDOUT",
        actor=SYSTEM_ADMIN,
    )
    set_id = holdout_set["eval_set"]["set_id"]

    # KNOWLEDGE_ADMIN lacks holdout.read -> cannot view HOLDOUT set
    with pytest.raises(EvaluationNotFoundError):
        svc.get_set_detail(set_id, actor=KNOWLEDGE_ADMIN)

    # SERVICE_OWNER also lacks holdout.read -> cannot view HOLDOUT set
    with pytest.raises(EvaluationNotFoundError):
        svc.get_set_detail(set_id, actor=SERVICE_OWNER)

    # Cross-unit actor cannot write or view
    with pytest.raises(EvaluationAuthorizationError):
        svc.create_case(
            title="非法跨單位案例",
            query="跨權限建立",
            owner_unit_id="IT Service Desk",
            provenance=ProvenanceSpec(source_type="MANUAL", source_id="m1"),
            actor=OTHER_UNIT_ADMIN,
        )


def test_ge1_a05_source_update_marks_needs_review_and_blocks_publish():
    """GE1-A05: Source version update marks revisions as NEEDS_REVIEW, blocking publication."""
    svc, _, _ = _setup_service()

    created = svc.create_case(
        title="資安通報作業準則",
        query="發現釣魚信件應通報何處？",
        owner_unit_id="IT Service Desk",
        behavior="ANSWER_WITH_CITATION",
        provenance=ProvenanceSpec(source_type="DOCUMENT", source_id="sec_policy_doc", source_version_id="v1"),
        actor=KNOWLEDGE_ADMIN,
    )
    rev = created["revision"]
    svc.submit_revision(rev["revision_id"], expected_etag=rev["etag"], actor=KNOWLEDGE_ADMIN)
    approved = svc.review_revision(
        rev["revision_id"],
        approve=True,
        reason="Approved against sec_policy_doc v1",
        expected_etag=rev["etag"] + 1,
        actor=SERVICE_OWNER,
    )["revision"]
    assert approved["status"] == "APPROVED"

    # Source document is updated to v2
    affected = svc.mark_source_needs_review(
        source_type="DOCUMENT",
        source_id="sec_policy_doc",
        new_version_id="v2",
        actor=KNOWLEDGE_ADMIN,
    )
    assert rev["revision_id"] in affected

    # Check case revision source_health is now NEEDS_REVIEW
    detail = svc.get_case_detail(created["case"]["case_id"], actor=KNOWLEDGE_ADMIN)
    assert detail["current_revision"]["source_health"] == "NEEDS_REVIEW"

    # Attempt to publish set containing this revision -> must fail
    eval_set = svc.create_set(
        name="資安題庫",
        owner_unit_ids=("IT Service Desk",),
        actor=KNOWLEDGE_ADMIN,
    )["eval_set"]
    draft = svc.create_set_version_draft(
        eval_set["set_id"],
        case_revision_ids=(rev["revision_id"],),
        actor=KNOWLEDGE_ADMIN,
    )["version"]

    with pytest.raises(EvaluationValidationError, match="source health NEEDS_REVIEW; cannot publish"):
        svc.publish_set_version(
            draft["set_version_id"],
            expected_etag=draft["etag"],
            actor=SERVICE_OWNER,
        )


def test_ge1_a06_idempotency_and_version_conflict():
    """GE1-A06: Idempotency-Key returns identical response; stale etag is rejected with 409."""
    svc, _, _ = _setup_service()

    # Create case with idempotency key
    res1 = svc.create_case(
        title="會議室預約",
        query="會議室如何借用？",
        owner_unit_id="IT Service Desk",
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="m2"),
        actor=KNOWLEDGE_ADMIN,
        idempotency_key="key_create_room_01",
    )

    # Replay identical request
    res2 = svc.create_case(
        title="會議室預約",
        query="會議室如何借用？",
        owner_unit_id="IT Service Desk",
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="m2"),
        actor=KNOWLEDGE_ADMIN,
        idempotency_key="key_create_room_01",
    )
    assert res1["case"]["case_id"] == res2["case"]["case_id"]

    # Version conflict test: submit with stale etag (expected 99, actual 1)
    rev_id = res1["revision"]["revision_id"]
    with pytest.raises(EvaluationVersionConflictError, match="Etag mismatch"):
        svc.submit_revision(rev_id, expected_etag=99, actor=KNOWLEDGE_ADMIN)


def test_ge1_a07_import_validation_and_csv_formula_sanitization():
    """GE1-A07: Dry-run diagnoses invalid rows without writing; CSV formula injection is sanitized."""
    svc, iem, _ = _setup_service()

    # Dry-run with error row
    malformed_jsonl = """
{"title": "有效題目 1", "query": "正常問題", "behavior": "ANSWER_WITH_CITATION"}
{"title": "", "query": "缺標題問題", "behavior": "ANSWER_WITH_CITATION"}
"""
    val_res = iem.validate_import(
        malformed_jsonl,
        file_format="JSONL",
        owner_unit_id="IT Service Desk",
        actor=KNOWLEDGE_ADMIN,
    )
    assert not val_res.is_valid
    assert val_res.error_rows == 1
    assert val_res.errors[0]["field"] == "title"

    # Valid JSONL dry-run and atomic commit
    valid_jsonl = """
{"title": "有效題目 A", "query": "問題 A", "behavior": "ANSWER_WITH_CITATION", "required_facts": ["重點一"]}
{"title": "有效題目 B", "query": "問題 B", "behavior": "REFUSE"}
"""
    val_ok = iem.validate_import(
        valid_jsonl,
        file_format="JSONL",
        owner_unit_id="IT Service Desk",
        actor=KNOWLEDGE_ADMIN,
    )
    assert val_ok.is_valid
    assert val_ok.valid_rows == 2

    # Commit staged batch
    created_ids = iem.commit_staged_import(
        val_ok.staged_import_id,
        owner_unit_id="IT Service Desk",
        actor=KNOWLEDGE_ADMIN,
    )
    assert len(created_ids) == 2

    # CSV formula injection test: title starts with '=cmd|'
    csv_payload = "title,query,behavior\n=SUM(1+1),計算公式問題,ANSWER_WITH_CITATION"
    val_csv = iem.validate_import(
        csv_payload,
        file_format="CSV",
        owner_unit_id="IT Service Desk",
        actor=KNOWLEDGE_ADMIN,
    )
    assert val_csv.is_valid
    iem.commit_staged_import(
        val_csv.staged_import_id,
        owner_unit_id="IT Service Desk",
        actor=KNOWLEDGE_ADMIN,
    )

    # Export to CSV -> verify leading '=' is prepended with single quote
    exported_csv = iem.export_cases(actor=AUDITOR, file_format="CSV")
    assert "'=SUM(1+1)" in exported_csv


def test_ge1_a08_candidate_generator_lifecycle():
    """GE1-A08: Candidate generator creates synthetic draft cases and tracks token/cost budget."""
    svc, _, cgm = _setup_service()

    job = cgm.start_generation_job(
        source_refs=(
            {"source_type": "FAQ", "source_id": "faq_hr_leave", "title": "休假規章", "version_id": "v1"},
        ),
        target_types=("ANSWER_WITH_CITATION", "CLARIFY", "REFUSE"),
        requested_count=3,
        owner_unit_id="HR",
        actor=KNOWLEDGE_ADMIN,
        limits={"max_tokens": 1000, "max_cost_usd": 0.10},
    )

    assert job["status"] == "COMPLETED"
    assert len(job["created_candidate_case_ids"]) == 3
    assert job["used_tokens"] > 0
    assert job["estimated_cost_usd"] > 0

    # Ensure all generated cases are in DRAFT status and marked SYNTHETIC
    for case_id in job["created_candidate_case_ids"]:
        detail = svc.get_case_detail(case_id, actor=KNOWLEDGE_ADMIN)
        rev = detail["current_revision"]
        assert rev["status"] == "DRAFT"
        assert rev["provenance"]["source_type"] == "SYNTHETIC"
        assert rev["provenance"]["generator_model"] == "gemini-2.5-flash"
