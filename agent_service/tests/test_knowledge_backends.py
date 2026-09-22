from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.contracts import (
    AgentRequest,
    ConversationIdentity,
    KnowledgeResult,
    MessageContent,
    UserContext,
    UserIdentity,
)
from agent_service.execution_context import ExecutionContext
from agent_service.knowledge_backends import (
    FirestoreKnowledgeBackendStateStore,
    KnowledgeBackendRouter,
)
from agent_service.settings import RagSettings


class FakeBackend:
    def __init__(self, name: str) -> None:
        self.name = name

    async def search(self, query, user_context, *, correlation_id=None):
        return KnowledgeResult(found=True, answer=query, backend=self.name)


class RequestAwareBackend:
    def __init__(self) -> None:
        self.request: AgentRequest | None = None

    async def search(
        self,
        query,
        user_context,
        *,
        correlation_id=None,
        request=None,
    ):
        self.request = request
        return KnowledgeResult(found=True, answer=query, backend="HYBRID")


class FakeSnapshot:
    def __init__(self, value: dict | None) -> None:
        self.exists = value is not None
        self._value = value

    def to_dict(self):
        return self._value


class FakeDocument:
    def __init__(self) -> None:
        self.value: dict | None = None

    async def get(self):
        return FakeSnapshot(self.value)

    async def set(self, value, merge=False):
        self.value = {**(self.value or {}), **value} if merge else value


@pytest.mark.asyncio
async def test_router_switches_backends_and_keeps_unavailable_reason() -> None:
    router = KnowledgeBackendRouter(
        {"HYBRID": FakeBackend("HYBRID"), "GEMINI_FILE_SEARCH": FakeBackend("GEMINI_FILE_SEARCH")},
        "HYBRID",
    )

    first = await router.search("first", UserContext())
    await router.select("GEMINI_FILE_SEARCH")
    second = await router.search("second", UserContext())

    assert first.backend == "HYBRID"
    assert second.backend == "GEMINI_FILE_SEARCH"
    assert (await router.status())["activeBackend"] == "GEMINI_FILE_SEARCH"


@pytest.mark.asyncio
async def test_router_keeps_request_backend_after_active_backend_switch(
    tmp_path: Path,
) -> None:
    router = KnowledgeBackendRouter(
        {
            "HYBRID": FakeBackend("HYBRID"),
            "GEMINI_FILE_SEARCH": FakeBackend("GEMINI_FILE_SEARCH"),
        },
        "HYBRID",
    )
    context = ExecutionContext.from_request(
        settings=RagSettings(
            data_dir=tmp_path,
            index_path=tmp_path / "index.json",
        ),
        correlation_id="correlation-1",
        request_id="request-1",
        tenant_id="tenant-1",
        knowledge_backend="HYBRID",
    )

    await router.select("GEMINI_FILE_SEARCH")
    result = await router.search(
        "question",
        UserContext(),
        execution_context=context,
    )

    assert result.backend == "HYBRID"
    assert context.selected_knowledge_backend == "HYBRID"


@pytest.mark.asyncio
async def test_router_keeps_pinned_service_after_hybrid_hot_reload(
    tmp_path: Path,
) -> None:
    """In-flight requests must keep the original Hybrid service instance."""
    original = FakeBackend("HYBRID-old")
    replacement = FakeBackend("HYBRID-new")
    router = KnowledgeBackendRouter({"HYBRID": original}, "HYBRID")
    context = ExecutionContext.from_request(
        settings=RagSettings(
            data_dir=tmp_path,
            index_path=tmp_path / "index.json",
        ),
        correlation_id="correlation-pin",
        request_id="request-pin",
        tenant_id="tenant-1",
    )

    first = await router.search(
        "before-reload",
        UserContext(),
        execution_context=context,
    )
    router.update_service("HYBRID", replacement)
    second = await router.search(
        "after-reload",
        UserContext(),
        execution_context=context,
    )

    assert first.backend == "HYBRID-old"
    assert second.backend == "HYBRID-old"
    assert context.pinned_knowledge_service is original


@pytest.mark.asyncio
async def test_router_forwards_evaluation_request_to_selected_backend() -> None:
    backend = RequestAwareBackend()
    router = KnowledgeBackendRouter({"HYBRID": backend}, "HYBRID")
    request = AgentRequest(
        requestId="evaluation-request",
        channel="evaluation",
        conversation=ConversationIdentity(tenantId="tenant-1"),
        user=UserIdentity(teamsUserId="evaluation-user"),
        message=MessageContent(text="Evaluate this question."),
    )

    await router.search("question", UserContext(), request=request)

    assert backend.request is request


@pytest.mark.asyncio
async def test_router_rejects_an_unavailable_backend() -> None:
    router = KnowledgeBackendRouter(
        {"HYBRID": FakeBackend("HYBRID")},
        "HYBRID",
        {"GEMINI_FILE_SEARCH": "尚未設定 GEMINI_FILE_SEARCH_STORE"},
    )

    with pytest.raises(ValueError, match="GEMINI_FILE_SEARCH_STORE"):
        await router.select("GEMINI_FILE_SEARCH")

    option = next(
        item for item in (await router.status())["options"] if item["id"] == "GEMINI_FILE_SEARCH"
    )
    assert option["available"] is False


@pytest.mark.asyncio
async def test_firestore_state_is_shared_across_router_instances() -> None:
    document = FakeDocument()
    first_store = FirestoreKnowledgeBackendStateStore(
        type(
            "Client",
            (),
            {
                "collection": lambda _self, _name: type(
                    "Collection", (), {"document": lambda _self, _name: document}
                )()
            },
        )(),
        "runtime_config",
        "HYBRID",
    )
    services = {
        "HYBRID": FakeBackend("HYBRID"),
        "GEMINI_FILE_SEARCH": FakeBackend("GEMINI_FILE_SEARCH"),
    }
    first = KnowledgeBackendRouter(services, "HYBRID", state_store=first_store)
    second = KnowledgeBackendRouter(services, "HYBRID", state_store=first_store)

    await first.select("GEMINI_FILE_SEARCH")

    assert await second.active_backend() == "GEMINI_FILE_SEARCH"
