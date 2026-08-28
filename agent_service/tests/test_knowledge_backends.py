from __future__ import annotations

import pytest

from agent_service.contracts import KnowledgeResult, UserContext
from agent_service.knowledge_backends import (
    FirestoreKnowledgeBackendStateStore,
    KnowledgeBackendRouter,
)


class FakeBackend:
    def __init__(self, name: str) -> None:
        self.name = name

    async def search(self, query, user_context, *, correlation_id=None):
        return KnowledgeResult(found=True, answer=query, backend=self.name)


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
async def test_router_rejects_an_unavailable_backend() -> None:
    router = KnowledgeBackendRouter(
        {"HYBRID": FakeBackend("HYBRID")},
        "HYBRID",
        {"GEMINI_FILE_SEARCH": "尚未設定 GEMINI_FILE_SEARCH_STORE"},
    )

    with pytest.raises(ValueError, match="GEMINI_FILE_SEARCH_STORE"):
        await router.select("GEMINI_FILE_SEARCH")

    option = next(
        item
        for item in (await router.status())["options"]
        if item["id"] == "GEMINI_FILE_SEARCH"
    )
    assert option["available"] is False


@pytest.mark.asyncio
async def test_firestore_state_is_shared_across_router_instances() -> None:
    document = FakeDocument()
    first_store = FirestoreKnowledgeBackendStateStore(
        type("Client", (), {
            "collection": lambda _self, _name: type(
                "Collection", (), {"document": lambda _self, _name: document}
            )()
        })(),
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
