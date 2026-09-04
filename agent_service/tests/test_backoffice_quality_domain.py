from pathlib import Path

import pytest

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.faq_domain.errors import (
    FaqAuthorizationError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)
from ai_ops_backoffice.quality_domain import FileQualityRepository, QualityService


WRITER = ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("IT",))
OWNER = ActorContext("owner", "Owner", "SERVICE_OWNER", ("IT",))


def seed_candidate(service: QualityService, event_id: str, case_type: str = "NO_ANSWER"):
    return service.add_candidate(
        source_type="EVENT",
        case_type=case_type,
        title="VPN 無答案",
        description="使用者 user@example.com 找不到答案",
        issue_type_id="vpn.connection_failed",
        question_cluster_id=None,
        owner_unit_id="IT",
        source_event_ids=(event_id,),
        conversation_refs=("conversation-1",),
        frequency=3,
        negative_rate=0.5,
        handoff_rate=0.25,
        estimated_cost_impact=20,
        actor=WRITER,
    )["candidate"]


def test_quality_candidates_merge_transition_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "quality.json"
    service = QualityService(FileQualityRepository(path))
    first = seed_candidate(service, "event-1")
    second = seed_candidate(service, "event-2", "NEGATIVE_FEEDBACK")
    replay = seed_candidate(service, "event-1")
    assert replay["candidate_id"] == first["candidate_id"]
    assert "user@example.com" not in first["description"]

    merged = service.merge_candidates(
        (first["candidate_id"], second["candidate_id"]),
        title="改善 VPN 回答覆蓋",
        description="補足錯誤碼與復原步驟",
        priority="HIGH",
        assignee_id="writer",
        target_due_at=None,
        actor=WRITER,
    )["case"]
    assert merged["frequency"] == 6
    assert merged["case_type"] == "OTHER"
    assert all(item["status"] == "MERGED" for item in service.list_candidates(actor=WRITER))

    case_id = merged["case_id"]
    triaged = service.transition_case(
        case_id,
        status="TRIAGED",
        reason="完成分流",
        resolution_type=None,
        expected_etag=1,
        actor=WRITER,
    )["case"]
    assert triaged["etag"] == 2
    with pytest.raises(FaqVersionConflictError):
        service.transition_case(
            case_id,
            status="IN_PROGRESS",
            reason=None,
            resolution_type=None,
            expected_etag=1,
            actor=WRITER,
        )
    with pytest.raises(FaqTransitionError):
        service.transition_case(
            case_id,
            status="RESOLVED",
            reason="too early",
            resolution_type="FAQ_UPDATED",
            expected_etag=2,
            actor=OWNER,
        )

    restarted = QualityService(FileQualityRepository(path))
    detail = restarted.case_detail(case_id, actor=OWNER)
    assert detail["case"]["status"] == "TRIAGED"
    assert len(detail["audit"]) == 2


def test_quality_terminal_reason_and_scope(tmp_path: Path) -> None:
    service = QualityService(FileQualityRepository(tmp_path / "quality.json"))
    candidate = seed_candidate(service, "event-1")
    merged = service.merge_candidates(
        (candidate["candidate_id"],),
        title="VPN gap",
        description="VPN gap",
        priority="MEDIUM",
        assignee_id=None,
        target_due_at=None,
        actor=WRITER,
    )["case"]
    with pytest.raises(FaqValidationError, match="reason"):
        service.transition_case(
            merged["case_id"],
            status="WONT_FIX",
            reason=None,
            resolution_type="ACCEPTED_RISK",
            expected_etag=1,
            actor=OWNER,
        )
    finance = ActorContext("finance", "Finance", "KNOWLEDGE_ADMIN", ("Finance",))
    assert service.list_cases(actor=finance) == []
    with pytest.raises(FaqAuthorizationError):
        service.case_detail(merged["case_id"], actor=finance)


def test_quality_case_links_faq_and_records_observation_evidence(tmp_path: Path) -> None:
    service = QualityService(FileQualityRepository(tmp_path / "quality.json"))
    candidate = seed_candidate(service, "event-observe")
    case = service.merge_candidates(
        (candidate["candidate_id"],), title="VPN improvement", description="Add FAQ",
        priority="HIGH", assignee_id="writer", target_due_at=None, actor=WRITER,
    )["case"]
    case = service.transition_case(
        case["case_id"], status="TRIAGED", reason="triaged", resolution_type=None,
        expected_etag=case["etag"], actor=WRITER,
    )["case"]
    case = service.transition_case(
        case["case_id"], status="IN_PROGRESS", reason=None, resolution_type=None,
        expected_etag=case["etag"], actor=WRITER,
    )["case"]
    case = service.link_content(
        case["case_id"], faq_id="faq-1", document_id=None,
        expected_etag=case["etag"], actor=WRITER,
    )["case"]
    observed = service.observe_faq(
        "faq-1",
        baseline_by_issue={
            "vpn.connection_failed": {"count": 30, "noAnswerRate": 0.5, "negativeFeedbackRate": 0.3},
        },
        actor=WRITER,
    )["items"][0]
    assert observed["status"] == "OBSERVING"
    assert observed["observation_baseline"]["count"] == 30
    refreshed = service.record_observation(
        case["case_id"], metrics={"count": 35, "noAnswerRate": 0.1, "negativeFeedbackRate": 0.05},
        expected_etag=observed["etag"], actor=WRITER,
    )["case"]
    resolved = service.transition_case(
        case["case_id"], status="RESOLVED", reason="rates improved",
        resolution_type="FAQ_UPDATED", expected_etag=refreshed["etag"], actor=OWNER,
    )["case"]
    assert resolved["status"] == "RESOLVED"
    assert resolved["observation_latest"]["noAnswerRate"] == 0.1


def test_question_cluster_corrections_create_immutable_revisions(tmp_path: Path) -> None:
    service = QualityService(FileQualityRepository(tmp_path / "quality.json"))
    first = seed_candidate(service, "event-1")
    second = seed_candidate(service, "event-2")
    generated = service.generate_clusters(actor=WRITER)
    assert len(generated["items"]) == 1
    assert generated["groupingMethod"] == "OWNER_UNIT_ISSUE_TYPE"
    cluster = generated["items"][0]
    assert cluster["grouping_method"] == "OWNER_UNIT_ISSUE_TYPE"
    renamed = service.correct_clusters(
        (cluster["cluster_id"],),
        action="RENAME",
        name="VPN 連線失敗群組",
        candidate_groups=(),
        actor=WRITER,
    )["items"][0]
    assert renamed["revision"] == 2
    assert renamed["parent_cluster_ids"] == [cluster["cluster_id"]]
    split = service.correct_clusters(
        (renamed["cluster_id"],),
        action="SPLIT",
        name="VPN 子群組",
        candidate_groups=((first["candidate_id"],), (second["candidate_id"],)),
        actor=WRITER,
    )["items"]
    assert len(split) == 2
    history = service.list_clusters(actor=WRITER)
    assert [item["status"] for item in history[:2]] == ["SUPERSEDED", "SUPERSEDED"]
    assert all(item["revision"] == 3 for item in split)