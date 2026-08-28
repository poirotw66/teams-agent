"""Tests for the Conversation Repository & Service (spec §18.4).

The same behavioral suite is parametrized to run against all three
implementations -- InMemoryConversationRepository (MEMORY),
FileConversationRepository (FILE) and FirestoreConversationRepository
(FIRESTORE) -- so every backend is held to identical behavior, per spec
§10.3. The Firestore runs are driven by ``fake_firestore.FakeFirestoreClient``:
no network, no credentials, no emulator.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fake_firestore import FakeFirestoreClient

from agent_service.contracts import ConversationMessage, PendingIssueContext
from agent_service.conversation import (
    ConversationService,
    FileConversationRepository,
    FirestoreConversationRepository,
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


@pytest.fixture(params=["memory", "file", "firestore"])
def repo_kind(request):
    return request.param


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def repository(repo_kind, clock, tmp_path):
    if repo_kind == "memory":
        return InMemoryConversationRepository(clock=clock)
    if repo_kind == "file":
        return FileConversationRepository(tmp_path / "conversations", clock=clock)
    return FirestoreConversationRepository(FakeFirestoreClient(), clock=clock)


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
        role="assistant",
        text="hello there",
        createdAt=clock(),
        correlationId="corr-1",
        followUpState="AWAITING_CLARIFICATION",
        pendingIssues=[
            PendingIssueContext(
                description="VPN 無法連線",
                missingInfo=["錯誤訊息或錯誤碼"],
                askedQuestions=["錯誤訊息或錯誤碼"],
                clarificationCount=1,
            )
        ],
    )
    await repository.save_message(created.conversationId, msg1)
    await repository.save_message(created.conversationId, msg2)

    recent = await repository.get_recent_messages(created.conversationId, limit=10)
    assert [m.text for m in recent] == ["hi", "hello there"]
    assert recent[0].correlationId == "corr-1"
    assert recent[1].role == "assistant"
    assert recent[1].followUpState == "AWAITING_CLARIFICATION"
    assert recent[1].pendingIssues[0].description == "VPN 無法連線"
    assert recent[1].pendingIssues[0].clarificationCount == 1


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


# --- FIRESTORE mode specific ------------------------------------------------


def make_firestore_repo(client: FakeFirestoreClient, clock, **overrides):
    kwargs = {"clock": clock}
    kwargs.update(overrides)
    return FirestoreConversationRepository(client, **kwargs)


async def test_firestore_survives_instance_replacement(clock):
    """The reason FIRESTORE mode exists: Cloud Run recycles instances.

    A brand-new repository object (i.e. a fresh Cloud Run instance) sharing
    only the backing store must see the previous instance's conversation.
    """
    client = FakeFirestoreClient()
    repo1 = make_firestore_repo(client, clock)
    created = await repo1.create_conversation(**KEY_A)
    await repo1.save_message(
        created.conversationId,
        ConversationMessage(role="user", text="before restart", createdAt=clock()),
    )

    repo2 = make_firestore_repo(client, clock)
    found = await repo2.find_conversation(**KEY_A, timeout_hours=24)
    assert found is not None
    assert found.conversationId == created.conversationId
    messages = await repo2.get_recent_messages(created.conversationId, limit=10)
    assert [m.text for m in messages] == ["before restart"]


async def test_firestore_interleaved_instances_do_not_lose_messages(clock):
    """Two instances appending concurrently must both survive.

    This is the failure mode an array-append (read-modify-write) would
    hit: each instance reads the same array and the later write drops the
    other's message. Message-per-document has no such race.
    """
    client = FakeFirestoreClient()
    repo1 = make_firestore_repo(client, clock)
    repo2 = make_firestore_repo(client, clock)
    created = await repo1.create_conversation(**KEY_A)

    await repo1.save_message(
        created.conversationId,
        ConversationMessage(role="user", text="from-instance-1", createdAt=clock()),
    )
    await repo2.save_message(
        created.conversationId,
        ConversationMessage(role="assistant", text="from-instance-2", createdAt=clock()),
    )

    messages = await repo1.get_recent_messages(created.conversationId, limit=10)
    assert {m.text for m in messages} == {"from-instance-1", "from-instance-2"}


async def test_firestore_orders_messages_sharing_a_timestamp(clock):
    """Insertion order must hold even when the clock does not advance."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    created = await repo.create_conversation(**KEY_A)

    same_instant = clock()
    for i in range(6):
        await repo.save_message(
            created.conversationId,
            ConversationMessage(role="user", text=f"msg-{i}", createdAt=same_instant),
        )

    messages = await repo.get_recent_messages(created.conversationId, limit=10)
    assert [m.text for m in messages] == [f"msg-{i}" for i in range(6)]
    # And the tail is still the *newest* tail, not an arbitrary slice.
    tail = await repo.get_recent_messages(created.conversationId, limit=2)
    assert [m.text for m in tail] == ["msg-4", "msg-5"]


async def test_firestore_save_message_rejects_unknown_conversation(clock):
    repo = make_firestore_repo(FakeFirestoreClient(), clock)
    with pytest.raises(LookupError):
        await repo.save_message(
            "no-such-conversation",
            ConversationMessage(role="user", text="orphan", createdAt=clock()),
        )


async def test_firestore_orphan_message_is_never_written(clock):
    """A rejected save must not leave a message document behind."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    with pytest.raises(LookupError):
        await repo.save_message(
            "no-such-conversation",
            ConversationMessage(role="user", text="orphan", createdAt=clock()),
        )
    assert client.document_count("conversations/") == 0


async def test_firestore_writes_expiry_for_ttl_policy(clock):
    """Every document carries expiresAt so a TTL policy can collect it (§10.2)."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock, retention_hours=24)
    created = await repo.create_conversation(**KEY_A)
    await repo.save_message(
        created.conversationId,
        ConversationMessage(role="user", text="hi", createdAt=clock()),
    )

    documents = client.all_documents()
    assert documents, "expected the repository to have written something"
    for path, data in documents.items():
        assert "expiresAt" in data, f"{path} has no expiresAt for the TTL policy"
        assert data["expiresAt"] == clock() + timedelta(hours=24)


async def test_firestore_expiry_advances_with_activity(clock):
    """Retention is measured from last activity, not from creation."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock, retention_hours=24)
    created = await repo.create_conversation(**KEY_A)
    created_expiry = client.all_documents()[f"conversations/{created.conversationId}"][
        "expiresAt"
    ]

    clock.advance(hours=3)
    await repo.save_message(
        created.conversationId,
        ConversationMessage(role="user", text="still here", createdAt=clock()),
    )
    updated = client.all_documents()[f"conversations/{created.conversationId}"]
    assert updated["expiresAt"] == created_expiry + timedelta(hours=3)
    # merge=True must not have dropped the rest of the document.
    assert updated["startedAt"] == created.startedAt
    assert updated["conversationKey"]


async def test_firestore_timeout_applies_even_if_ttl_has_not_collected(clock):
    """A stale-but-present document is still treated as no conversation.

    TTL collection is best-effort and lags; §10.2's timeout must not
    depend on it.
    """
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    created = await repo.create_conversation(**KEY_A)
    clock.advance(hours=25)

    assert await repo.find_conversation(**KEY_A, timeout_hours=24) is None
    # The document is deliberately still there -- nothing deleted it.
    assert client.read(f"conversations/{created.conversationId}") is not None


async def test_firestore_key_document_id_is_safe_and_isolating(clock):
    """Isolation keys are hashed: no '/' in the id, no collisions across users."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    await repo.create_conversation(
        tenant_id="tenant/with/slashes", teams_conversation_id="conv-1", teams_user_id="user-1"
    )
    await repo.create_conversation(
        tenant_id="tenant/with/slashes", teams_conversation_id="conv-1", teams_user_id="user-2"
    )

    key_paths = [p for p in client.paths() if p.startswith("conversations_keys/")]
    assert len(key_paths) == 2, "each user must get its own key document"
    for path in key_paths:
        doc_id = path.split("/", 1)[1]
        assert "/" not in doc_id


async def test_firestore_context_carries_message_tail_for_ticket_offer_check(clock):
    """The workflow reads conversation.messages[-1]; it must be populated."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    created = await repo.create_conversation(**KEY_A)
    for text in ["first", "second", "latest"]:
        await repo.save_message(
            created.conversationId,
            ConversationMessage(role="assistant", text=text, createdAt=clock()),
        )

    found = await repo.find_conversation(**KEY_A, timeout_hours=24)
    assert found is not None
    assert found.messages[-1].text == "latest"


async def test_firestore_context_tail_is_bounded(clock):
    """A long conversation must not pull every message into memory."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock, context_message_limit=4)
    created = await repo.create_conversation(**KEY_A)
    for i in range(12):
        await repo.save_message(
            created.conversationId,
            ConversationMessage(role="user", text=f"msg-{i}", createdAt=clock()),
        )

    found = await repo.find_conversation(**KEY_A, timeout_hours=24)
    assert [m.text for m in found.messages] == ["msg-8", "msg-9", "msg-10", "msg-11"]


async def test_firestore_tolerates_malformed_message_document(clock):
    """One bad document must not fail the whole request (cf. FILE mode)."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    created = await repo.create_conversation(**KEY_A)
    await repo.save_message(
        created.conversationId,
        ConversationMessage(role="user", text="good", createdAt=clock()),
    )
    # Hand-write a document with no usable createdAt.
    client.write(
        f"conversations/{created.conversationId}/messages/99999999999999999999-000000-deadbeef",
        {"role": "user", "text": "bad", "createdAt": None},
    )

    messages = await repo.get_recent_messages(created.conversationId, limit=10)
    assert [m.text for m in messages] == ["good"]


async def test_firestore_reads_iso_string_timestamps(clock):
    """Timestamps written as ISO strings still parse (defensive path)."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    created = await repo.create_conversation(**KEY_A)
    client.write(
        f"conversations/{created.conversationId}",
        {
            "conversationKey": "k",
            "tenantId": "tenant-1",
            "startedAt": "2026-01-01T00:00:00+00:00",
            "lastActivityAt": "2026-01-01T00:00:00+00:00",
        },
    )

    found = await repo.find_conversation(**KEY_A, timeout_hours=24)
    assert found is not None
    assert found.startedAt == datetime(2026, 1, 1, tzinfo=timezone.utc)


async def test_firestore_missing_conversation_document_is_absent_not_error(clock):
    """A key pointing at a collected/deleted conversation reads as absent."""
    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    created = await repo.create_conversation(**KEY_A)
    # Simulate TTL having collected the conversation but not yet the key.
    client._documents.pop(f"conversations/{created.conversationId}")

    assert await repo.find_conversation(**KEY_A, timeout_hours=24) is None


async def test_firestore_never_logs_message_text(clock, caplog):
    """Spec §15.2: message text must never reach the logs."""
    import logging

    client = FakeFirestoreClient()
    repo = make_firestore_repo(client, clock)
    created = await repo.create_conversation(**KEY_A)
    with caplog.at_level(logging.DEBUG, logger="agent_service.conversation"):
        await repo.save_message(
            created.conversationId,
            ConversationMessage(role="user", text="my password is hunter2", createdAt=clock()),
        )
    assert "hunter2" not in caplog.text
    assert created.conversationId in caplog.text


class TestFakeFirestoreMatchesTheRealSdk:
    """Pin the Fake to the real client's surface.

    Every other Firestore test drives a Fake, so a Fake that has drifted
    from ``google-cloud-firestore`` would let a broken repository pass.
    These tests introspect the real SDK when it is installed (the
    ``firestore`` extra) and skip otherwise, so they add no install
    requirement to the default suite.
    """

    @staticmethod
    def real_sdk(module: str = "google.cloud.firestore"):
        """Import a real-SDK module, or skip when the extra isn't installed.

        Every real-SDK import in this class must go through here. A bare
        ``import google.cloud...`` raises ``ModuleNotFoundError`` instead of
        skipping, which turns "the optional extra is absent" into a failing
        default suite.
        """
        return pytest.importorskip(
            module,
            reason="install the 'firestore' extra to check the Fake against the real SDK",
        )

    def test_client_collection_and_document_chain_exists(self):
        sdk = self.real_sdk()
        assert callable(sdk.AsyncClient.collection)
        assert callable(sdk.AsyncCollectionReference.document)
        assert callable(sdk.AsyncDocumentReference.collection)

    def test_document_set_accepts_merge(self):
        import inspect

        sdk = self.real_sdk()
        parameters = inspect.signature(sdk.AsyncDocumentReference.set).parameters
        assert "merge" in parameters
        assert parameters["merge"].default is False

    def test_order_by_accepts_field_path_and_direction(self):
        import inspect

        sdk = self.real_sdk()
        parameters = inspect.signature(sdk.AsyncQuery.order_by).parameters
        assert "field_path" in parameters
        assert "direction" in parameters
        # The literal the repository passes must be the SDK's own constant.
        assert sdk.Query.DESCENDING == "DESCENDING"

    def test_snapshot_exposes_exists_and_to_dict(self):
        base_document = self.real_sdk("google.cloud.firestore_v1.base_document")
        snapshot = base_document.DocumentSnapshot
        assert isinstance(snapshot.exists, property)
        assert callable(snapshot.to_dict)

    def test_fake_mirrors_the_same_surface(self):
        """The Fake side of the same contract, checked without the SDK."""
        client = FakeFirestoreClient()
        document = client.collection("c").document("d")
        assert callable(document.get)
        assert callable(document.set)
        assert callable(document.collection)
        query = client.collection("c").order_by("sortKey", direction="DESCENDING").limit(1)
        assert callable(query.stream)

    def test_fake_rejects_descending_name_ordering_like_real_firestore(self):
        """Real Firestore needs a composite index for this; the Fake must too.

        Regression guard: the repository originally ordered by ``__name__``
        descending, which passed against a permissive Fake and failed
        against live Firestore with FAILED_PRECONDITION.
        """
        from fake_firestore import FakeFirestoreError

        client = FakeFirestoreClient()
        with pytest.raises(FakeFirestoreError):
            client.collection("c").order_by("__name__", direction="DESCENDING")

    async def test_fake_snapshot_exposes_exists_and_to_dict(self):
        client = FakeFirestoreClient()
        document = client.collection("c").document("d")
        assert (await document.get()).exists is False
        await document.set({"a": 1})
        snapshot = await document.get()
        assert snapshot.exists is True
        assert snapshot.to_dict() == {"a": 1}


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


def test_build_repository_firestore_mode(tmp_path):
    settings = make_settings(
        tmp_path,
        conversation_repository_mode="FIRESTORE",
        conversation_firestore_collection="poc_conversations",
    )
    repo = build_repository(settings, firestore_client=FakeFirestoreClient())
    assert isinstance(repo, FirestoreConversationRepository)


async def test_build_repository_firestore_mode_uses_configured_collection(tmp_path, clock):
    client = FakeFirestoreClient()
    settings = make_settings(
        tmp_path,
        conversation_repository_mode="FIRESTORE",
        conversation_firestore_collection="poc_conversations",
    )
    repo = build_repository(settings, clock=clock, firestore_client=client)
    await repo.create_conversation(**KEY_A)

    assert all(path.startswith("poc_conversations") for path in client.paths())
    assert client.document_count("poc_conversations_keys/") == 1


async def test_build_repository_firestore_retention_is_separate_from_timeout(tmp_path, clock):
    client = FakeFirestoreClient()
    settings = make_settings(
        tmp_path,
        conversation_repository_mode="FIRESTORE",
        conversation_timeout_hours=48,
        conversation_retention_days=2,
    )
    repo = build_repository(settings, clock=clock, firestore_client=client)
    created = await repo.create_conversation(**KEY_A)

    document = client.read(f"conversations/{created.conversationId}")
    assert document["expiresAt"] == clock() + timedelta(days=2)


async def test_build_repository_firestore_tail_covers_history_window(tmp_path, clock):
    """The repository tail must never be the binding constraint on history."""
    client = FakeFirestoreClient()
    settings = make_settings(
        tmp_path,
        conversation_repository_mode="FIRESTORE",
        max_history_messages=10,
    )
    repo = build_repository(settings, clock=clock, firestore_client=client)
    created = await repo.create_conversation(**KEY_A)
    for i in range(15):
        await repo.save_message(
            created.conversationId,
            ConversationMessage(role="user", text=f"msg-{i}", createdAt=clock()),
        )

    found = await repo.find_conversation(**KEY_A, timeout_hours=24)
    assert len(found.messages) >= settings.max_history_messages


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
