from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import mask_text

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqVersionConflictError,
)


from .models import *  # noqa: F403

class SyncRepository(Protocol):
    def load(self) -> SyncState: ...

    def mutate(self, operation: Mutation) -> dict[str, Any]: ...

class InMemorySyncRepository:
    def __init__(self) -> None:
        self._state = SyncState()
        self._lock = threading.RLock()

    def load(self) -> SyncState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        with self._lock:
            next_state, result = operation(self._state.model_copy(deep=True))
            if next_state.revision != self._state.revision + 1:
                raise FaqVersionConflictError("sync state revision must increment")
            self._state = next_state
            return result

class FileSyncRepository(InMemorySyncRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")

    def _read(self) -> SyncState:
        if not self._path.exists():
            return SyncState()
        return SyncState.model_validate_json(self._path.read_text(encoding="utf-8"))

    def load(self) -> SyncState:
        with self._lock:
            return self._read()

    def _write(self, state: SyncState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(state.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            directory = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        import fcntl

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                current = self._read()
                next_state, result = operation(current)
                if next_state.revision != current.revision + 1:
                    raise FaqVersionConflictError("sync state revision must increment")
                self._write(next_state)
                return result
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

class FirestoreSyncRepository:
    def __init__(
        self,
        client: Any,
        *,
        collection: str = "ai_ops_sync_state",
        transaction_runner: Any | None = None,
    ) -> None:
        self._client = client
        self._state = client.collection(collection).document("current")
        self._transaction_runner = transaction_runner

    def load(self) -> SyncState:
        snapshot = self._state.get()
        return SyncState.model_validate(snapshot.to_dict()) if snapshot.exists else SyncState()

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        def transaction_operation(transaction: Any) -> dict[str, Any]:
            snapshot = self._state.get(transaction=transaction)
            current = SyncState.model_validate(snapshot.to_dict()) if snapshot.exists else SyncState()
            next_state, result = operation(current)
            if next_state.revision != current.revision + 1:
                raise FaqVersionConflictError("sync state revision must increment")
            transaction.set(self._state, next_state.model_dump(mode="python"))
            return result

        if self._transaction_runner is not None:
            return self._transaction_runner(transaction_operation, self._client.transaction())
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("FIRESTORE sync repository requires google-cloud-firestore") from error
        return transactional(transaction_operation)(self._client.transaction())

