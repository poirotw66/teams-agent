"""Tests for the Conversation Repository & Service (spec §18.4).

The same behavioral suite is parametrized to run against both the
InMemoryConversationRepository (Fake, MEMORY mode) and the
FileConversationRepository (FILE mode) so the two implementations are held
to identical behavior, per spec §10.3.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_service.contracts import ConversationMessage
from agent_service.conversation import (
    ConversationService,
    FileConversationRepository,
    InMemoryConversationRepository,
    build_repository,
)
from agent_service.settings import RagSettings


class FakeClock:
    """A controllable clock so timeout tests never need real sleeping."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> None:
        self._now = self._now + timedelta(**kwargs)


@pytest.fixture(params=["memory", "file"])
def repo_kind(request):
    return request.param


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def repository(repo_kind, clock, tmp_path):
    if repo_kind == "memory":
        return InMemoryConversationRepository(clock=clock)
    return FileConversationRepository(tmp_path / "conversations", clock=clock)


def make_settings(tmp_path: Path, **overrides) -> RagSettings:
    kwargs = {
        "data_dir": tmp_path,
        "index_path": tmp_path / "index.json",
        "conversation_timeout_hours": 24,
        "conversation_history_rounds": 5,
        "max_history_messages": 10,
    }
    kwargs.update(overrides)
    return RagSettings(**kwargs)


KEY_A = {"tenant_id": "tenant-1", "teams_conversation_id": "conv-1", "teams_user_id": "user-1"}


# --- ConversationRepository behavior (both implementations) ---------------


async def test_find_conversation_returns_none_when_absent(repository):
    result = await repository.find_conversation(**KEY_A, timeout_hours=24)
    assert result is None


async def test_create_then_find_returns_active_conversation(repository):
    created = await repository.create_conversation(**KEY_A)
    found = await repository.find_conversation(**KEY_A, timeout_hours=24)
    assert found is not None
    assert found.conversationId == created.conversationId


async def test_timeout_conversation_not_reused(repository, clock):
    created = await repository.create_conversation(**KEY_A)
    clock.advance(hours=25)
    found = await repository.find_conversation(**KEY_A, timeout_hours=24)
    assert found is None

    # A new conversation created after the timeout must get a new id.
    recreated = await repository.create_conversation(**KEY_A)
    assert recreated.conversationId != created.conversationId
    found_again = await repository.find_conversation(**KEY_A, timeout_hours=24)
    assert found_again is not None
    assert found_again.conversationId == recreated.conversationId


async def test_within_timeout_conversation_reused_and_activity_advances(repository, clock):
    created = await repository.create_conversation(**KEY_A)
    clock.advance(hours=1)
    message = ConversationMessage(role="user", text="hello", createdAt=clock())
    await repository.save_message(created.conversationId, message)

    found = await repository.find_conversation(**KEY_A, timeout_hours=24)
    assert found is not None
    assert found.conversationId == created.conversationId
    assert found.lastActivityAt == message.createdAt
    assert found.lastActivityAt > created.startedAt


async def test_save_message_then_get_recent_messages_roundtrip(repository, clock):
    created = await repository.create_conversation(**KEY_A)
    msg1 = ConversationMessage(
        role="user", text="hi", createdAt=clock(), correlationId="corr-1"
    )
    clock.advance(minutes=1)
    msg2 = ConversationMessage(
        role="assistant", text="hello there", createdAt=clock(), correlationId="corr-1"
    )
    await repository.save_message(created.conversationId, msg1)
    await repository.save_message(created.conversationId, msg2)

    recent = await repository.get_recent_messages(created.conversationId, limit=10)
    assert [m.text for m in recent] == ["hi", "hello there"]
    assert recent[0].correlationId == "corr-1"
    assert recent[1].role == "assistant"


async def test_get_recent_messages_respects_limit_and_is_most_recent(repository, clock):
    created = await repository.create_conversation(**KEY_A)
    for i in range(5):
        msg = ConversationMessage(role="user", text=f"msg-{i}", createdAt=clock())
        await repository.save_message(created.conversationId, msg)
        clock.advance(minutes=1)

    recent = await repository.get_recent_messages(created.conversationId, limit=2)
    # Oldest-first ordering of the *tail* (most recent) messages.
    assert [m.text for m in recent] == ["msg-3", "msg-4"]


async def test_different_users_are_isolated(repository):
    ctx_a = await repository.create_conversation(
        tenant_id="tenant-1", teams_conversation_id="conv-1", teams_user_id="user-1"
    )
    ctx_b = await repository.create_conversation(
        tenant_id="tenant-1", teams_conversation_id="conv-1", teams_user_id="user-2"
    )
    assert ctx_a.conversationId != ctx_b.conversationId

    found_a = await repository.find_conversation(
        tenant_id="tenant-1",
        teams_conversation_id="conv-1",
        teams_user_id="user-1",
        timeout_hours=24,
    )
    found_b = await repository.find_conversation(
        tenant_id="tenant-1",
        teams_conversation_id="conv-1",
        teams_user_id="user-2",
        timeout_hours=24,
    )
    assert found_a.conversationId == ctx_a.conversationId
    assert found_b.conversationId == ctx_b.conversationId


async def test_different_conversations_are_isolated(repository):
    ctx_a = await repository.create_conversation(
        tenant_id="tenant-1", teams_conversation_id="conv-1", teams_user_id="user-1"
    )
    ctx_b = await repository.create_conversation(
        tenant_id="tenant-1", teams_conversation_id="conv-2", teams_user_id="user-1"
    )
    assert ctx_a.conversationId != ctx_b.conversationId

    await repository.save_message(
        ctx_a.conversationId,
        ConversationMessage(role="user", text="secret-a", createdAt=datetime.now(timezone.utc)),
    )

    messages_a = await repository.get_recent_messages(ctx_a.conversationId, limit=10)
    messages_b = await repository.get_recent_messages(ctx_b.conversationId, limit=10)
    assert [m.text for m in messages_a] == ["secret-a"]
    assert messages_b == []


async def test_different_tenants_are_isolated(repository):
    ctx_a = await repository.create_conversation(
        tenant_id="tenant-1", teams_conversation_id="conv-1", teams_user_id="user-1"
    )
    ctx_b = await repository.create_conversation(
        tenant_id="tenant-2", teams_conversation_id="conv-1", teams_user_id="user-1"
    )
    assert ctx_a.conversationId != ctx_b.conversationId


# --- FILE mode specific ----------------------------------------------------


async def test_file_repository_persists_across_fresh_instance(tmp_path, clock):
    store_path = tmp_path / "conversations"
    repo1 = FileConversationRepository(store_path, clock=clock)
    created = await repo1.create_conversation(**KEY_A)
    await repo1.save_message(
        created.conversationId,
        ConversationMessage(role="user", text="persisted", createdAt=clock()),
    )

    # A brand-new repository instance pointed at the same path must see it.
    repo2 = FileConversationRepository(store_path, clock=clock)
    found = await repo2.find_conversation(**KEY_A, timeout_hours=24)
    assert found is not None
    assert found.conversationId == created.conversationId
    messages = await repo2.get_recent_messages(created.conversationId, limit=10)
    assert [m.text for m in messages] == ["persisted"]


async def test_file_repository_tolerates_corrupt_conversation_file(tmp_path, clock):
    store_path = tmp_path / "conversations"
    repo = FileConversationRepository(store_path, clock=clock)
    created = await repo.create_conversation(**KEY_A)

    # Corrupt the underlying JSON file directly.
    conversation_file = store_path / f"{created.conversationId}.json"
    conversation_file.write_text("{not valid json", encoding="utf-8")

    found = await repo.find_conversation(**KEY_A, timeout_hours=24)
    assert found is None
    messages = await repo.get_recent_messages(created.conversationId, limit=10)
    assert messages == []


async def test_file_repository_tolerates_corrupt_index_file(tmp_path, clock):
    store_path = tmp_path / "conversations"
    repo = FileConversationRepository(store_path, clock=clock)
    await repo.create_conversation(**KEY_A)

    index_file = store_path / "index.json"
    index_file.write_text("not json at all", encoding="utf-8")

    # Corrupt index is treated as empty -> no active conversation found,
    # but the call must not raise.
    found = await repo.find_conversation(**KEY_A, timeout_hours=24)
    assert found is None


# --- build_repository factory ----------------------------------------------


def test_build_repository_memory_mode(tmp_path):
    settings = make_settings(tmp_path, conversation_repository_mode="MEMORY")
    repo = build_repository(settings)
    assert isinstance(repo, InMemoryConversationRepository)


def test_build_repository_file_mode(tmp_path):
    settings = make_settings(
        tmp_path,
        conversation_repository_mode="FILE",
        conversation_store_path=tmp_path / "store",
    )
    repo = build_repository(settings)
    assert isinstance(repo, FileConversationRepository)


def test_build_repository_rejects_unknown_mode(tmp_path):
    settings = make_settings(tmp_path, conversation_repository_mode="MONGO")
    with pytest.raises(ValueError):
        build_repository(settings)


# --- ConversationService: policy (timeout, trimming) ------------------------


async def test_service_load_or_create_creates_new_when_absent(repository, tmp_path, clock):
    settings = make_settings(tmp_path)
    service = ConversationService(repository, settings, clock=clock)
    ctx = await service.load_or_create(**KEY_A)
    assert ctx.conversationId


async def test_service_load_or_create_reuses_within_timeout(repository, tmp_path, clock):
    settings = make_settings(tmp_path, conversation_timeout_hours=24)
    service = ConversationService(repository, settings, clock=clock)
    ctx1 = await service.load_or_create(**KEY_A)
    clock.advance(hours=1)
    ctx2 = await service.load_or_create(**KEY_A)
    assert ctx1.conversationId == ctx2.conversationId


async def test_service_load_or_create_new_conversation_after_timeout(repository, tmp_path, clock):
    settings = make_settings(tmp_path, conversation_timeout_hours=24)
    service = ConversationService(repository, settings, clock=clock)
    ctx1 = await service.load_or_create(**KEY_A)
    clock.advance(hours=25)
    ctx2 = await service.load_or_create(**KEY_A)
    assert ctx1.conversationId != ctx2.conversationId


async def test_service_record_message_and_get_history_order(repository, tmp_path, clock):
    settings = make_settings(tmp_path, max_history_messages=10, conversation_history_rounds=5)
    service = ConversationService(repository, settings, clock=clock)
    ctx = await service.load_or_create(**KEY_A)

    await service.record_message(
        ctx.conversationId, role="user", text="q1", correlation_id="c1"
    )
    clock.advance(seconds=1)
    await service.record_message(
        ctx.conversationId, role="assistant", text="a1", correlation_id="c1"
    )

    history = await service.get_history(ctx.conversationId)
    assert [m.text for m in history] == ["q1", "a1"]
    assert history[0].role == "user"
    assert history[1].role == "assistant"


async def test_service_history_honors_max_history_messages(repository, tmp_path, clock):
    settings = make_settings(tmp_path, max_history_messages=3, conversation_history_rounds=10)
    service = ConversationService(repository, settings, clock=clock)
    ctx = await service.load_or_create(**KEY_A)

    for i in range(6):
        role = "user" if i % 2 == 0 else "assistant"
        await service.record_message(ctx.conversationId, role=role, text=f"m{i}")
        clock.advance(seconds=1)

    history = await service.get_history(ctx.conversationId)
    assert len(history) <= 3
    # Must be the most recent messages, in chronological order.
    assert [m.text for m in history] == ["m3", "m4", "m5"]


async def test_service_history_honors_conversation_history_rounds(repository, tmp_path, clock):
    # 3 full user/assistant rounds = 6 messages; cap history_messages high so
    # only the rounds bound is exercised.
    settings = make_settings(tmp_path, max_history_messages=50, conversation_history_rounds=2)
    service = ConversationService(repository, settings, clock=clock)
    ctx = await service.load_or_create(**KEY_A)

    expected_texts = []
    for round_idx in range(3):
        await service.record_message(
            ctx.conversationId, role="user", text=f"q{round_idx}"
        )
        clock.advance(seconds=1)
        await service.record_message(
            ctx.conversationId, role="assistant", text=f"a{round_idx}"
        )
        clock.advance(seconds=1)
        expected_texts.append((f"q{round_idx}", f"a{round_idx}"))

    history = await service.get_history(ctx.conversationId)
    # Only the last 2 rounds (round_idx 1 and 2) should survive.
    assert [m.text for m in history] == ["q1", "a1", "q2", "a2"]


async def test_service_history_applies_both_bounds_together(repository, tmp_path, clock):
    # max_history_messages is tighter than what conversation_history_rounds
    # alone would allow; the tighter bound must win, keeping most-recent.
    settings = make_settings(tmp_path, max_history_messages=3, conversation_history_rounds=10)
    service = ConversationService(repository, settings, clock=clock)
    ctx = await service.load_or_create(**KEY_A)

    for round_idx in range(3):
        await service.record_message(ctx.conversationId, role="user", text=f"q{round_idx}")
        clock.advance(seconds=1)
        await service.record_message(ctx.conversationId, role="assistant", text=f"a{round_idx}")
        clock.advance(seconds=1)

    history = await service.get_history(ctx.conversationId)
    assert len(history) <= 3
    assert [m.text for m in history] == ["a1", "q2", "a2"]
