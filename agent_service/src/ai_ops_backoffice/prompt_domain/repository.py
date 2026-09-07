from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from agent_service import extractor
from agent_service.extractor import SYSTEM_PROMPT
from agent_service.operations.access import ActorContext

from ..faq_domain.errors import FaqAuthorizationError, FaqNotFoundError, FaqValidationError


from .models import *  # noqa: F403

class PromptRepository(Protocol):
    def load(self) -> PromptState: ...

    def mutate(self, operation: Mutation) -> dict[str, Any]: ...

class InMemoryPromptRepository:
    def __init__(self) -> None:
        self._state = PromptState()
        self._lock = threading.RLock()

    def load(self) -> PromptState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        with self._lock:
            next_state, result = operation(self._state.model_copy(deep=True))
            if next_state.revision != self._state.revision + 1:
                raise RuntimeError("prompt state revision must increment")
            self._state = next_state
            return result

class FilePromptRepository(InMemoryPromptRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")

    def _read(self) -> PromptState:
        if not self._path.exists():
            return PromptState()
        return PromptState.model_validate_json(self._path.read_text(encoding="utf-8"))

    def load(self) -> PromptState:
        with self._lock:
            return self._read()

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        import fcntl

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                current = self._read()
                next_state, result = operation(current)
                if next_state.revision != current.revision + 1:
                    raise RuntimeError("prompt state revision must increment")
                temporary = self._path.with_suffix(f"{self._path.suffix}.{uuid.uuid4().hex}.tmp")
                try:
                    with temporary.open("x", encoding="utf-8") as handle:
                        handle.write(next_state.model_dump_json(indent=2))
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, self._path)
                finally:
                    temporary.unlink(missing_ok=True)
                return result
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

class FirestorePromptRepository:
    def __init__(self, client: Any, *, collection: str = "ai_ops_prompt_poc_state") -> None:
        self._client = client
        self._state = client.collection(collection).document("current")

    def load(self) -> PromptState:
        snapshot = self._state.get()
        return PromptState.model_validate(snapshot.to_dict()) if snapshot.exists else PromptState()

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("FIRESTORE prompt repository requires google-cloud-firestore") from error

        @transactional
        def run(transaction: Any) -> dict[str, Any]:
            snapshot = self._state.get(transaction=transaction)
            current = PromptState.model_validate(snapshot.to_dict()) if snapshot.exists else PromptState()
            next_state, result = operation(current)
            if next_state.revision != current.revision + 1:
                raise RuntimeError("prompt state revision must increment")
            transaction.set(self._state, next_state.model_dump(mode="python"))
            return result

        return run(self._client.transaction())

