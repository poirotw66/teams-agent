from __future__ import annotations

import fcntl
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from agent_service.usage import _MODEL_RATES_USD, PRICING_VERSION

from .models import HistoricalPricingRule, Mutation, PricingState


class PricingRepository(Protocol):
    def load(self) -> PricingState: ...

    def mutate(self, operation: Mutation) -> dict[str, Any]: ...


def _initial_pricing_state() -> PricingState:
    now = datetime.now(UTC)
    initial_rule = HistoricalPricingRule(
        version=PRICING_VERSION,
        effective_at=datetime(2026, 8, 31, 0, 0, tzinfo=UTC),
        exchange_rate=31.70,
        rates=dict(_MODEL_RATES_USD),
        description="Initial standard production pricing baseline.",
        created_by="system",
        created_at=now,
    )
    return PricingState(
        revision=1,
        exchange_rate=31.70,
        pricing_version=PRICING_VERSION,
        rates=dict(_MODEL_RATES_USD),
        history=(initial_rule,),
        audits=(),
    )


class InMemoryPricingRepository:
    def __init__(self, initial_state: PricingState | None = None) -> None:
        self._state = initial_state or _initial_pricing_state()
        self._lock = threading.RLock()

    def load(self) -> PricingState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        with self._lock:
            next_state, result = operation(self._state.model_copy(deep=True))
            if next_state.revision != self._state.revision + 1:
                raise RuntimeError("Pricing state revision must increment")
            self._state = next_state
            return result


class FilePricingRepository(InMemoryPricingRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            initial = _initial_pricing_state()
            self._path.write_text(initial.model_dump_json(indent=2), encoding="utf-8")

    def _read(self) -> PricingState:
        if not self._path.exists():
            return _initial_pricing_state()
        return PricingState.model_validate_json(self._path.read_text(encoding="utf-8"))

    def load(self) -> PricingState:
        with self._lock:
            return self._read()

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                current = self._read()
                next_state, result = operation(current)
                if next_state.revision != current.revision + 1:
                    raise RuntimeError("Pricing state revision must increment")
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


class FirestorePricingRepository:
    def __init__(
        self,
        client: Any,
        *,
        collection: str = "ai_ops_pricing_state",
        transaction_runner: Any | None = None,
    ) -> None:
        self._client = client
        self._state = client.collection(collection).document("current")
        self._transaction_runner = transaction_runner

    def load(self) -> PricingState:
        snapshot = self._state.get()
        return (
            PricingState.model_validate(snapshot.to_dict())
            if snapshot.exists
            else _initial_pricing_state()
        )

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        def transaction_operation(transaction: Any) -> dict[str, Any]:
            snapshot = self._state.get(transaction=transaction)
            current = (
                PricingState.model_validate(snapshot.to_dict())
                if snapshot.exists
                else _initial_pricing_state()
            )
            next_state, result = operation(current)
            if next_state.revision != current.revision + 1:
                raise RuntimeError("Pricing state revision must increment")
            transaction.set(self._state, next_state.model_dump(mode="python"))
            return result

        if self._transaction_runner is not None:
            return self._transaction_runner(
                transaction_operation, self._client.transaction()
            )
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:
            raise RuntimeError(
                "FIRESTORE pricing repository requires google-cloud-firestore"
            ) from error
        return transactional(transaction_operation)(self._client.transaction())

