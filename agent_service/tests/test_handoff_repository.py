import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from agent_service.handoff import (
    ActiveHandoffCaseExistsError,
    CaseSummary,
    HandoffCase,
    HandoffPermissionError,
    HandoffStatus,
    HandoffVersionConflictError,
    InMemoryHandoffRepository,
    InvalidHandoffTransitionError,
)
from agent_service.handoff_repository import FileHandoffRepository

NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def make_case(case_id="case-1", requester="user-1", conversation="conv-1"):
    return HandoffCase(
        caseId=case_id,
        sessionId=f"session-{case_id}",
        tenantId="tenant-1",
        conversationId=conversation,
        requesterId=requester,
        status=HandoffStatus.OFFERED,
        summary=CaseSummary(
            issue="VPN 無法登入",
            userNeed="恢復 VPN 使用",
            unresolvedReason="知識庫無可靠答案",
            requestedOutcome="取得協助",
            generatedAt=NOW,
        ),
        createdAt=NOW,
        updatedAt=NOW,
        sessionExpiresAt=NOW + timedelta(hours=24),
        retentionExpiresAt=NOW + timedelta(days=730),
        correlationId="corr-1",
    )


@pytest.mark.asyncio
async def test_memory_repository_enforces_conversation_uniqueness() -> None:
    repository = InMemoryHandoffRepository(clock=lambda: NOW)
    first = make_case()
    second = make_case("case-2", requester="other-user")

    results = await asyncio.gather(
        repository.create_case(first),
        repository.create_case(second),
        return_exceptions=True,
    )

    assert sum(isinstance(item, HandoffCase) for item in results) == 1
    assert sum(isinstance(item, ActiveHandoffCaseExistsError) for item in results) == 1


@pytest.mark.asyncio
async def test_memory_repository_rejects_stale_and_invalid_transitions() -> None:
    repository = InMemoryHandoffRepository(clock=lambda: NOW)
    case = await repository.create_case(make_case())

    with pytest.raises(HandoffVersionConflictError):
        await repository.transition(
            case.caseId,
            HandoffStatus.OFFERED,
            HandoffStatus.SUMMARY_REVIEW,
            expected_version=99,
        )
    with pytest.raises(InvalidHandoffTransitionError):
        await repository.transition(
            case.caseId,
            HandoffStatus.OFFERED,
            HandoffStatus.DEMO_ACTIVE,
            expected_version=case.version,
        )


@pytest.mark.asyncio
async def test_expired_case_restores_ai_routing_and_keeps_record() -> None:
    future = NOW + timedelta(hours=25)
    repository = InMemoryHandoffRepository(clock=lambda: future)
    await repository.create_case(make_case())

    assert await repository.get_active_case("tenant-1", "conv-1", "user-1") is None
    stored = await repository.get_case("case-1")
    assert stored is not None and stored.status == HandoffStatus.EXPIRED
    assert stored.retentionExpiresAt == NOW + timedelta(days=730)
    assert [event.eventType for event in await repository.list_events("case-1")] == [
        "handoff.expired"
    ]


@pytest.mark.asyncio
async def test_only_original_requester_can_close() -> None:
    repository = InMemoryHandoffRepository(clock=lambda: NOW)
    case = await repository.create_case(make_case())
    case = await repository.transition(
        case.caseId,
        HandoffStatus.OFFERED,
        HandoffStatus.SUMMARY_REVIEW,
        case.version,
    )
    case = await repository.transition(
        case.caseId,
        HandoffStatus.SUMMARY_REVIEW,
        HandoffStatus.DEMO_ACTIVE,
        case.version,
    )

    with pytest.raises(HandoffPermissionError):
        await repository.close_case(case.caseId, "intruder", case.version)
    assert (await repository.get_case(case.caseId)).status == HandoffStatus.DEMO_ACTIVE


@pytest.mark.asyncio
async def test_file_repository_survives_fresh_instance(tmp_path) -> None:
    path = tmp_path / "handoffs.json"
    first = FileHandoffRepository(path, clock=lambda: NOW)
    case = await first.create_case(make_case())
    reviewed = await first.transition(
        case.caseId,
        HandoffStatus.OFFERED,
        HandoffStatus.SUMMARY_REVIEW,
        case.version,
    )

    second = FileHandoffRepository(path, clock=lambda: NOW)
    restored = await second.get_active_case("tenant-1", "conv-1", "user-1")

    assert restored is not None
    assert restored.status == HandoffStatus.SUMMARY_REVIEW
    assert restored.version == reviewed.version
