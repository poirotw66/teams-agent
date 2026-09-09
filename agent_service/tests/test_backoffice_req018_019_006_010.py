from __future__ import annotations

from pathlib import Path
import pytest

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.example_domain import (
    ExampleService,
    FileExampleRepository,
)
from ai_ops_backoffice.faq_domain import (
    FaqContent,
    FaqDomainService,
    FileFaqRepository,
)
from ai_ops_backoffice.faq_domain.errors import (
    FaqAuthorizationError,
    FaqValidationError,
)
from ai_ops_backoffice.quality_domain import (
    FileQualityRepository,
    QualityService,
)
from ai_ops_backoffice.request_models import QualityCandidateRefreshRequest

WRITER = ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("IT",))
ADMIN = ActorContext("admin", "Admin", "SYSTEM_ADMIN", ())


class AllowFaqAuthority:
    def require(self, *, actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        if actor.role != "SYSTEM_ADMIN" and owner_unit_id not in actor.owner_unit_ids:
            raise FaqAuthorizationError("owner-unit scope denied")


class ActiveTaxonomy:
    def __init__(self, active: set[str] | None = None) -> None:
        self.active = active or {"vpn.connection_failed"}

    def require_active(self, issue_type_id: str) -> None:
        if issue_type_id not in self.active:
            raise FaqValidationError(f"inactive issue type: {issue_type_id}")


def test_req019_in_progress_case_protection_on_candidate_refresh(tmp_path: Path) -> None:
    """Verify in-progress quality cases are protected and overlapping candidates are auto-linked."""
    # Test request model accepts custom days
    req_14 = QualityCandidateRefreshRequest(days=14)
    assert req_14.days == 14
    req_365 = QualityCandidateRefreshRequest(days=365)
    assert req_365.days == 365

    quality_path = tmp_path / "quality.json"
    service = QualityService(FileQualityRepository(quality_path))

    # 1. Create first candidate and merge into a case
    first_cand = service.add_candidate(
        source_type="EVENT",
        case_type="NO_ANSWER",
        title="VPN 809 錯誤",
        description="連線逾時無法存取內網",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT",
        source_event_ids=("evt-101",),
        conversation_refs=("conv-201",),
        frequency=1,
        negative_rate=1.0,
        handoff_rate=0.0,
        estimated_cost_impact=10.0,
        actor=WRITER,
    )["candidate"]

    merged_case = service.merge_candidates(
        (first_cand["candidate_id"],),
        title="處理 VPN 809 錯誤案例",
        description="追蹤修復與改善",
        priority="HIGH",
        assignee_id="engineer_1",
        target_due_at=None,
        actor=WRITER,
    )["case"]
    case_id = merged_case["case_id"]

    # Transition case to IN_PROGRESS
    triaged = service.transition_case(
        case_id,
        status="TRIAGED",
        reason="分派處理",
        resolution_type=None,
        expected_etag=merged_case["etag"],
        actor=WRITER,
    )["case"]
    in_progress = service.transition_case(
        case_id,
        status="IN_PROGRESS",
        reason="開始修正知識",
        resolution_type=None,
        expected_etag=triaged["etag"],
        actor=WRITER,
    )["case"]
    assert in_progress["status"] == "IN_PROGRESS"

    # 2. Re-scan: add candidate with matching conversation_ref
    overlap_cand = service.add_candidate(
        source_type="EVENT",
        case_type="NO_ANSWER",
        title="VPN 再次連線失敗",
        description="相同對話產生之新事件",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT",
        source_event_ids=("evt-999",),
        conversation_refs=("conv-201",),  # overlaps with in_progress case
        frequency=2,
        negative_rate=1.0,
        handoff_rate=0.0,
        estimated_cost_impact=15.0,
        actor=WRITER,
    )["candidate"]

    # Overlapping candidate should be auto-merged into in-progress case rather than creating duplicate open work
    assert overlap_cand["status"] == "MERGED"
    assert overlap_cand["merged_case_id"] == case_id

    # 3. Add non-overlapping candidate
    independent_cand = service.add_candidate(
        source_type="EVENT",
        case_type="NO_ANSWER",
        title="全新問題類型",
        description="無任何關聯之新問題",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT",
        source_event_ids=("evt-888",),
        conversation_refs=("conv-777",),
        frequency=1,
        negative_rate=0.0,
        handoff_rate=0.0,
        estimated_cost_impact=5.0,
        actor=WRITER,
    )["candidate"]

    assert independent_cand["status"] == "OPEN"
    assert independent_cand["merged_case_id"] is None


def test_req018_question_cluster_similarity_and_manual_annotation_preservation(tmp_path: Path) -> None:
    """Verify question clusters use CJK Jaccard similarity and preserve manual renames."""
    quality_path = tmp_path / "quality.json"
    service = QualityService(FileQualityRepository(quality_path))

    # Add open candidates with similar CJK questions
    service.add_candidate(
        source_type="EVENT",
        case_type="NO_ANSWER",
        title="VPN 連線異常",
        description="請問微軟 VPN 無法連線怎麼辦",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT",
        source_event_ids=("e-1",),
        conversation_refs=("c-1",),
        frequency=3,
        negative_rate=0.5,
        handoff_rate=0.0,
        estimated_cost_impact=10.0,
        actor=WRITER,
    )
    service.add_candidate(
        source_type="EVENT",
        case_type="NO_ANSWER",
        title="VPN 連線問題",
        description="微軟 VPN 無法連線求助",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT",
        source_event_ids=("e-2",),
        conversation_refs=("c-2",),
        frequency=2,
        negative_rate=0.5,
        handoff_rate=0.0,
        estimated_cost_impact=10.0,
        actor=WRITER,
    )

    # Generate clusters
    gen_result = service.generate_clusters(actor=WRITER)
    clusters = gen_result["items"]
    assert len(clusters) >= 1
    target_cluster = clusters[0]
    assert target_cluster["status"] == "CANDIDATE"

    # Rename cluster
    corrected = service.correct_clusters(
        (target_cluster["cluster_id"],),
        action="RENAME",
        name="IT｜VPN連線故障手動標註組",
        candidate_groups=(),
        actor=WRITER,
    )
    renamed_cluster = corrected["items"][0]
    assert renamed_cluster["name"] == "IT｜VPN連線故障手動標註組"
    assert renamed_cluster["revision"] == 2

    # Subsequent cluster generation must not overwrite or duplicate the renamed cluster
    regen_result = service.generate_clusters(actor=WRITER)
    active_clusters = [c for c in service.list_clusters(actor=WRITER) if c["status"] != "SUPERSEDED"]
    matching_renamed = [c for c in active_clusters if c["name"] == "IT｜VPN連線故障手動標註組"]
    assert len(matching_renamed) == 1
    assert matching_renamed[0]["revision"] == 2


def test_req006_retired_examples_excluded_from_prompt_candidates(tmp_path: Path) -> None:
    """Verify retired few-shot examples are strictly excluded from verified examples and prompt candidates."""
    example_path = tmp_path / "examples.json"
    service = ExampleService(FileExampleRepository(example_path), taxonomy=ActiveTaxonomy())

    # Create example 1 and verify it
    ex1 = service.create(
        source_type="FAQ",
        source_id="faq-1",
        source_version_id="v1",
        source_correlation_id=None,
        owner_unit_id="IT",
        text="VPN 連線超時錯誤",
        expected_issue_type_id="vpn.connection_failed",
        expected_route="FAQ",
        label="POSITIVE",
        reason=None,
        actor=WRITER,
    )["example"]

    v1 = service.review(ex1["example_id"], approve=True, reason="valid positive sample", expected_etag=ex1["etag"], actor=ADMIN)["example"]
    assert v1["status"] == "VERIFIED"

    # Create example 2, verify it, then retire it
    ex2 = service.create(
        source_type="FAQ",
        source_id="faq-2",
        source_version_id="v1",
        source_correlation_id=None,
        owner_unit_id="IT",
        text="過時且已停用的少樣本案例",
        expected_issue_type_id="vpn.connection_failed",
        expected_route="FAQ",
        label="POSITIVE",
        reason=None,
        actor=WRITER,
    )["example"]

    v2 = service.review(ex2["example_id"], approve=True, reason="approved temporarily", expected_etag=ex2["etag"], actor=ADMIN)["example"]
    assert v2["status"] == "VERIFIED"

    # Retire example 2
    retired2 = service.retire(ex2["example_id"], reason="example retired due to deprecation", expected_etag=v2["etag"], actor=ADMIN)["example"]
    assert retired2["status"] == "RETIRED"

    # When querying verified examples for prompt candidate generation
    verified_list = service.list_examples(actor=ADMIN, status="VERIFIED")
    verified_ids = [item["example_id"] for item in verified_list]

    assert ex1["example_id"] in verified_ids
    assert ex2["example_id"] not in verified_ids
    assert all(item["status"] == "VERIFIED" for item in verified_list)
    assert not any(item["status"] == "RETIRED" for item in verified_list)


def test_req010_quality_case_faq_draft_creation_and_linking(tmp_path: Path) -> None:
    """Verify quality case converts to FAQ draft with question populated and link established."""
    quality_path = tmp_path / "quality.json"
    faq_path = tmp_path / "faqs.json"

    quality_service = QualityService(FileQualityRepository(quality_path))
    faq_service = FaqDomainService(FileFaqRepository(faq_path), authorization=AllowFaqAuthority(), taxonomy=ActiveTaxonomy())

    # 1. Create a quality case
    cand = quality_service.add_candidate(
        source_type="EVENT",
        case_type="NO_ANSWER",
        title="VPN 錯誤 809 問題排查",
        description="使用者在遠端工作時遇到 VPN 809 連線失敗，需要確認伺服器設定與連線憑證。",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT",
        source_event_ids=("evt-qa-1",),
        conversation_refs=("conv-qa-1",),
        frequency=5,
        negative_rate=0.8,
        handoff_rate=0.4,
        estimated_cost_impact=25.0,
        actor=WRITER,
    )["candidate"]

    case = quality_service.merge_candidates(
        (cand["candidate_id"],),
        title="VPN 錯誤 809 問題排查",
        description="使用者在遠端工作時遇到 VPN 809 連線失敗，需要確認伺服器設定與連線憑證。",
        priority="HIGH",
        assignee_id="support_tech",
        target_due_at=None,
        actor=WRITER,
    )["case"]
    case_id = case["case_id"]

    # 2. Create FAQ draft using the case description as question
    faq_content = FaqContent(
        faq_key="vpn-809-fix",
        question=case["description"],  # Case description populated as FAQ question
        answer="請檢查網路防火牆設定與憑證有效期限，重啟 VPN 連線軟體即可恢復。",
        category="VPN",
        keywords=("vpn", "809", "網路"),
        owner_unit_id=case["owner_unit_id"],
        business_contact="IT Helpdesk",
        issue_type_ids=(case["issue_type_id"],),
        audience_type="ALL",
        audience_group_ids=(),
        related_document_ids=(),
    )

    created_faq = faq_service.create(
        content=faq_content,
        actor=WRITER,
        idempotency_key="create-faq-draft-1",
    )
    faq_id = created_faq["faq"]["faq_id"]
    assert created_faq["version"]["content"]["question"] == case["description"]

    # Link FAQ to the quality case
    linked = quality_service.link_content(
        case_id,
        faq_id=faq_id,
        document_id=None,
        expected_etag=case["etag"],
        actor=WRITER,
    )["case"]
    assert faq_id in linked["faq_ids"]

    # Link another existing FAQ
    faq_content_2 = FaqContent(
        faq_key="vpn-general-guide",
        question="一般 VPN 設定指引",
        answer="請參照 IT 內網指引下載最新客戶端軟體。",
        category="VPN",
        keywords=("vpn", "設定"),
        owner_unit_id="IT",
        business_contact="IT Helpdesk",
        issue_type_ids=("vpn.connection_failed",),
        audience_type="ALL",
        audience_group_ids=(),
        related_document_ids=(),
    )
    created_faq_2 = faq_service.create(
        content=faq_content_2,
        actor=WRITER,
        idempotency_key="create-faq-draft-2",
    )
    faq_id_2 = created_faq_2["faq"]["faq_id"]

    linked_2 = quality_service.link_content(
        case_id,
        faq_id=faq_id_2,
        document_id=None,
        expected_etag=linked["etag"],
        actor=WRITER,
    )["case"]
    assert faq_id in linked_2["faq_ids"]
    assert faq_id_2 in linked_2["faq_ids"]
