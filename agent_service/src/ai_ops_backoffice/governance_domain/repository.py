from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .errors import GovernanceConflictError
from .models import GovernanceState

Mutation = Callable[[GovernanceState], tuple[GovernanceState, dict[str, Any]]]


class GovernanceRepository(Protocol):
    def load(self) -> GovernanceState: ...

    def mutate(self, operation: Mutation) -> dict[str, Any]: ...


class InMemoryGovernanceRepository:
    def __init__(self) -> None:
        self._state = GovernanceState()
        self._lock = threading.RLock()

    def load(self) -> GovernanceState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        with self._lock:
            next_state, result = operation(self._state.model_copy(deep=True))
            if next_state.revision != self._state.revision + 1:
                raise GovernanceConflictError("governance state revision must increment")
            self._state = next_state
            return result


class FileGovernanceRepository(InMemoryGovernanceRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")

    def _read(self) -> GovernanceState:
        if not self._path.exists():
            return GovernanceState()
        return GovernanceState.model_validate_json(self._path.read_text(encoding="utf-8"))

    def load(self) -> GovernanceState:
        with self._lock:
            return self._read()

    def _write(self, state: GovernanceState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(state.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
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
                    raise GovernanceConflictError("governance state revision must increment")
                self._write(next_state)
                return result
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


class FirestoreGovernanceRepository:
    def __init__(
        self,
        client: Any,
        *,
        collection: str = "ai_ops_governance_state",
        transaction_runner: Any | None = None,
    ) -> None:
        self._client = client
        self._state = client.collection(collection).document("current")
        self._transaction_runner = transaction_runner

    def load(self) -> GovernanceState:
        snapshot = self._state.get()
        if not snapshot.exists:
            return GovernanceState()
        return GovernanceState.model_validate(snapshot.to_dict())

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        def transaction_operation(transaction: Any) -> dict[str, Any]:
            snapshot = self._state.get(transaction=transaction)
            current = (
                GovernanceState.model_validate(snapshot.to_dict())
                if snapshot.exists
                else GovernanceState()
            )
            next_state, result = operation(current)
            if next_state.revision != current.revision + 1:
                raise GovernanceConflictError("governance state revision must increment")
            transaction.set(self._state, next_state.model_dump(mode="python"))
            return result

        if self._transaction_runner is not None:
            return self._transaction_runner(transaction_operation, self._client.transaction())
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("FIRESTORE governance repository requires google-cloud-firestore") from error
        return transactional(transaction_operation)(self._client.transaction())
