from __future__ import annotations

import hashlib
import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import mask_text, redact_secrets

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)


from .models import *  # noqa: F403

class QualityRepository(Protocol):
    def load(self) -> QualityState: ...

    def mutate(self, operation: Mutation) -> dict[str, Any]: ...

class InMemoryQualityRepository:
    def __init__(self) -> None:
        self._state = QualityState()
        self._lock = threading.RLock()

    def load(self) -> QualityState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        with self._lock:
            next_state, result = operation(self._state.model_copy(deep=True))
            if next_state.revision != self._state.revision + 1:
                raise FaqVersionConflictError("quality state revision must increment")
            self._state = next_state
            return result

class FileQualityRepository(InMemoryQualityRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")

    def _read_file(self) -> QualityState:
        if not self._path.exists():
            return QualityState()
        return QualityState.model_validate_json(self._path.read_text(encoding="utf-8"))

    def load(self) -> QualityState:
        with self._lock:
            return self._read_file()

    def _write_file(self, state: QualityState) -> None:
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
                current = self._read_file()
                next_state, result = operation(current)
                if next_state.revision != current.revision + 1:
                    raise FaqVersionConflictError("quality state revision must increment")
                self._write_file(next_state)
                return result
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

class FirestoreQualityRepository:
    def __init__(
        self,
        client: Any,
        *,
        collection: str = "ai_ops_quality_state",
        transaction_runner: Any | None = None,
    ) -> None:
        self._client = client
        self._state = client.collection(collection).document("current")
        self._transaction_runner = transaction_runner

    def load(self) -> QualityState:
        snapshot = self._state.get()
        return (
            QualityState.model_validate(snapshot.to_dict())
            if getattr(snapshot, "exists", False)
            else QualityState()
        )

    def _run_transaction(self, operation: Any) -> Any:
        if self._transaction_runner is not None:
            return self._transaction_runner(operation, self._client.transaction())
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:  # pragma: no cover
            raise RuntimeError(
                "FIRESTORE quality repository requires google-cloud-firestore"
            ) from error
        return transactional(operation)(self._client.transaction())

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        def transaction_operation(transaction: Any) -> dict[str, Any]:
            snapshot = self._state.get(transaction=transaction)
            current = (
                QualityState.model_validate(snapshot.to_dict())
                if getattr(snapshot, "exists", False)
                else QualityState()
            )
            next_state, result = operation(current)
            if next_state.revision != current.revision + 1:
                raise FaqVersionConflictError("quality state revision must increment")
            transaction.set(self._state, next_state.model_dump(mode="python"))
            return result

        return self._run_transaction(transaction_operation)

