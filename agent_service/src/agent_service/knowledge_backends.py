"""Runtime-selectable Knowledge Service routing for local/UAT evaluation."""

from __future__ import annotations

import inspect
from threading import Lock
from typing import Any, Protocol

from .contracts import KnowledgeResult, UserContext
from .knowledge import KnowledgeService, LlmCallCounter
from .settings import RagSettings


class KnowledgeBackendStateStore(Protocol):
    async def get(self) -> str: ...

    async def set(self, backend: str) -> None: ...


class MemoryKnowledgeBackendStateStore:
    def __init__(self, initial_backend: str) -> None:
        self._backend = initial_backend
        self._lock = Lock()

    async def get(self) -> str:
        with self._lock:
            return self._backend

    async def set(self, backend: str) -> None:
        with self._lock:
            self._backend = backend


class FirestoreKnowledgeBackendStateStore:
    def __init__(self, client: Any, collection: str, default_backend: str) -> None:
        self._document = client.collection(collection).document("knowledge_backend")
        self._default_backend = default_backend

    async def get(self) -> str:
        snapshot = await self._document.get()
        if not snapshot.exists:
            return self._default_backend
        return (snapshot.to_dict() or {}).get("backend") or self._default_backend

    async def set(self, backend: str) -> None:
        await self._document.set({"backend": backend}, merge=True)


def build_backend_state_store(settings: RagSettings) -> KnowledgeBackendStateStore:
    if settings.knowledge_backend_state_mode == "MEMORY":
        return MemoryKnowledgeBackendStateStore(settings.knowledge_service_mode)
    try:
        from google.cloud.firestore import AsyncClient
    except ImportError as exc:  # pragma: no cover - Cloud image installs the extra
        raise RuntimeError(
            "KNOWLEDGE_BACKEND_STATE_MODE=FIRESTORE requires google-cloud-firestore."
        ) from exc
    kwargs: dict[str, str] = {}
    if settings.conversation_firestore_project:
        kwargs["project"] = settings.conversation_firestore_project
    if settings.conversation_firestore_database:
        kwargs["database"] = settings.conversation_firestore_database
    return FirestoreKnowledgeBackendStateStore(
        AsyncClient(**kwargs),
        settings.knowledge_backend_state_collection,
        settings.knowledge_service_mode,
    )


class KnowledgeBackendRouter:
    """Route each knowledge lookup to one of the pre-built backends.

    The service map is immutable after startup. Switching only replaces the
    active backend name, while an in-flight lookup keeps the service snapshot
    it started with.
    """

    def __init__(
        self,
        services: dict[str, KnowledgeService],
        active_backend: str,
        unavailable: dict[str, str] | None = None,
        state_store: KnowledgeBackendStateStore | None = None,
    ) -> None:
        if active_backend not in services:
            raise ValueError(f"Knowledge backend is unavailable: {active_backend}")
        self._services = dict(services)
        self._state_store = state_store or MemoryKnowledgeBackendStateStore(active_backend)
        self._unavailable = dict(unavailable or {})

    async def active_backend(self) -> str:
        backend = await self._state_store.get()
        return backend if backend in self._services else next(iter(self._services))

    async def select(self, backend: str) -> None:
        if backend not in self._services:
            raise ValueError(
                self._unavailable.get(backend, f"Knowledge backend is unavailable: {backend}")
            )
        await self._state_store.set(backend)

    async def status(self) -> dict[str, object]:
        active = await self.active_backend()
        labels = {
            "HYBRID": "HYBRID（本機索引）",
            "GEMINI_FILE_SEARCH": "Gemini File Search",
        }
        backend_names = list(dict.fromkeys([*labels, *self._services, *self._unavailable]))
        return {
            "activeBackend": active,
            "options": [
                {
                    "id": name,
                    "label": labels.get(name, name),
                    "available": name in self._services,
                    "reason": self._unavailable.get(name),
                }
                for name in backend_names
            ],
        }

    async def search(
        self,
        query: str,
        user_context: UserContext,
        *,
        correlation_id: str | None = None,
        call_counter: LlmCallCounter | None = None,
    ) -> KnowledgeResult:
        service = self._services[await self.active_backend()]
        parameters = inspect.signature(service.search).parameters
        kwargs: dict[str, object] = {"correlation_id": correlation_id}
        if "call_counter" in parameters:
            kwargs["call_counter"] = call_counter
        return await service.search(query, user_context, **kwargs)
