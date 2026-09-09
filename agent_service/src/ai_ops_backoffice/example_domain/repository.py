from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import MASKING_POLICY_VERSION, mask_text, redact_secrets

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)


from .models import *  # noqa: F403

class ExampleRepository(Protocol):
    def list_examples(self) -> list[ExampleRecord]: ...

    def get(self, example_id: str) -> ExampleRecord | None: ...

    def list_audit(self, example_id: str) -> list[ExampleAuditEvent]: ...

    def replay(self, key: str | None, action: str, fingerprint: str) -> dict[str, Any] | None: ...

    def commit(
        self,
        record: ExampleRecord,
        audit: ExampleAuditEvent,
        *,
        expected_etag: int | None,
        idempotency_key: str | None,
        action: str,
        request_fingerprint: str,
        result: dict[str, Any],
    ) -> dict[str, Any]: ...

    def purge_expired(
        self,
        *,
        now: datetime,
        retention_days: int = 365,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]: ...

class InMemoryExampleRepository:
    def __init__(self) -> None:
        self._state = ExampleState()
        self._lock = threading.RLock()

    def _load(self) -> ExampleState:
        return self._state.model_copy(deep=True)

    def _save(self, state: ExampleState) -> None:
        self._state = state

    def list_examples(self) -> list[ExampleRecord]:
        with self._lock:
            return sorted(self._load().examples, key=lambda item: item.updated_at, reverse=True)

    def get(self, example_id: str) -> ExampleRecord | None:
        with self._lock:
            return next((item for item in self._load().examples if item.example_id == example_id), None)

    def list_audit(self, example_id: str) -> list[ExampleAuditEvent]:
        with self._lock:
            return [item for item in self._load().audits if item.example_id == example_id]

    def replay(self, key: str | None, action: str, fingerprint: str) -> dict[str, Any] | None:
        if not key:
            return None
        with self._lock:
            item = next((item for item in self._load().idempotency if item.key == key), None)
            if item is None:
                return None
            if item.action != action or item.request_fingerprint != fingerprint:
                raise FaqIdempotencyConflictError(
                    "idempotency key was reused with a different example request"
                )
            return deepcopy(item.result)

    def commit(
        self,
        record: ExampleRecord,
        audit: ExampleAuditEvent,
        *,
        expected_etag: int | None,
        idempotency_key: str | None,
        action: str,
        request_fingerprint: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            state = self._load()
            if idempotency_key:
                replay = self.replay(idempotency_key, action, request_fingerprint)
                if replay is not None:
                    return replay
            current = next(
                (item for item in state.examples if item.example_id == record.example_id),
                None,
            )
            if expected_etag is None and current is not None:
                raise FaqVersionConflictError("example already exists")
            if expected_etag is not None and current is None:
                raise FaqNotFoundError(record.example_id)
            if current is not None and current.etag != expected_etag:
                raise FaqVersionConflictError("example was changed by another request")
            if record.etag != (expected_etag or 0) + 1:
                raise FaqVersionConflictError("next example etag must increment")
            examples = [item for item in state.examples if item.example_id != record.example_id]
            examples.append(record)
            idempotency = list(state.idempotency)
            if idempotency_key:
                idempotency.append(
                    ExampleIdempotencyRecord(
                        key=idempotency_key,
                        action=action,
                        request_fingerprint=request_fingerprint,
                        result=result,
                    )
                )
            self._save(
                ExampleState(
                    examples=tuple(examples),
                    audits=(*state.audits, audit),
                    idempotency=tuple(idempotency),
                )
            )
            return deepcopy(result)

    def purge_expired(
        self,
        *,
        now: datetime,
        retention_days: int = 365,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._load()
            cutoff = now - timedelta(days=retention_days)
            kept_examples: list[ExampleRecord] = []
            removed_ids: list[str] = []
            for ex in state.examples:
                if ex.status == "RETIRED":
                    retention_start = ex.retired_at or ex.updated_at
                    if retention_start < cutoff:
                        removed_ids.append(ex.example_id)
                        continue
                elif ex.status == "REJECTED":
                    retention_start = ex.updated_at
                    if retention_start < cutoff:
                        removed_ids.append(ex.example_id)
                        continue
                kept_examples.append(ex)

            if not removed_ids:
                return {"removed": 0, "removed_ids": []}

            audit = ExampleAuditEvent(
                audit_id=str(uuid.uuid4()),
                example_id="RETENTION_PURGE",
                action="EXAMPLE_RETENTION_PURGED",
                actor_id=actor.user_id if actor else "system.retention",
                actor_role=actor.role if actor else "SYSTEM",
                owner_unit_id="ALL",
                before={"exampleCount": len(state.examples), "purgedCount": len(removed_ids)},
                after={"exampleCount": len(kept_examples), "purgedIds": removed_ids},
                reason=f"Purged {len(removed_ids)} retired/rejected examples past {retention_days} days retention.",
                occurred_at=now,
            )
            self._save(
                ExampleState(
                    examples=tuple(kept_examples),
                    audits=(*state.audits, audit),
                    idempotency=state.idempotency,
                )
            )
            return {"removed": len(removed_ids), "removed_ids": removed_ids}

class FileExampleRepository(InMemoryExampleRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")

    def _load(self) -> ExampleState:
        if not self._path.exists():
            return ExampleState()
        return ExampleState.model_validate_json(self._path.read_text(encoding="utf-8"))

    def _save(self, state: ExampleState) -> None:
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

    def commit(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        import fcntl

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                return super().commit(*args, **kwargs)
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def purge_expired(
        self,
        *,
        now: datetime,
        retention_days: int = 365,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        import fcntl

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                return super().purge_expired(
                    now=now,
                    retention_days=retention_days,
                    actor=actor,
                )
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

class FirestoreExampleRepository:
    def __init__(
        self,
        client: Any,
        *,
        collection_prefix: str = "ai_ops_faq",
        transaction_runner: Any | None = None,
    ) -> None:
        self._client = client
        self._transaction_runner = transaction_runner
        self._examples = client.collection(f"{collection_prefix}_examples")
        self._audits = client.collection(f"{collection_prefix}_example_audit")
        self._idempotency = client.collection(f"{collection_prefix}_example_idempotency")

    @staticmethod
    def _read(reference: Any) -> dict[str, Any] | None:
        snapshot = reference.get()
        return snapshot.to_dict() if getattr(snapshot, "exists", False) else None

    def list_examples(self) -> list[ExampleRecord]:
        return sorted(
            (ExampleRecord.model_validate(item.to_dict()) for item in self._examples.stream()),
            key=lambda item: item.updated_at,
            reverse=True,
        )

    def get(self, example_id: str) -> ExampleRecord | None:
        payload = self._read(self._examples.document(example_id))
        return ExampleRecord.model_validate(payload) if payload else None

    def list_audit(self, example_id: str) -> list[ExampleAuditEvent]:
        return [
            ExampleAuditEvent.model_validate(item.to_dict())
            for item in self._audits.where("example_id", "==", example_id).stream()
        ]

    def replay(self, key: str | None, action: str, fingerprint: str) -> dict[str, Any] | None:
        if not key:
            return None
        payload = self._read(self._idempotency.document(key))
        if payload is None:
            return None
        if payload["action"] != action or payload["request_fingerprint"] != fingerprint:
            raise FaqIdempotencyConflictError(
                "idempotency key was reused with a different example request"
            )
        return deepcopy(payload["result"])

    def _run_transaction(self, operation: Any) -> Any:
        if self._transaction_runner is not None:
            return self._transaction_runner(operation, self._client.transaction())
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:  # pragma: no cover - optional dependency guard
            raise RuntimeError(
                "FIRESTORE example repository requires google-cloud-firestore"
            ) from error
        return transactional(operation)(self._client.transaction())

    def commit(
        self,
        record: ExampleRecord,
        audit: ExampleAuditEvent,
        *,
        expected_etag: int | None,
        idempotency_key: str | None,
        action: str,
        request_fingerprint: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        record_ref = self._examples.document(record.example_id)
        idem_ref = self._idempotency.document(idempotency_key) if idempotency_key else None

        def operation(transaction: Any) -> dict[str, Any]:
            if idem_ref is not None:
                previous = idem_ref.get(transaction=transaction)
                if getattr(previous, "exists", False):
                    payload = previous.to_dict()
                    if payload["action"] != action or payload["request_fingerprint"] != request_fingerprint:
                        raise FaqIdempotencyConflictError(
                            "idempotency key was reused with a different example request"
                        )
                    return deepcopy(payload["result"])
            current = record_ref.get(transaction=transaction)
            if expected_etag is None and getattr(current, "exists", False):
                raise FaqVersionConflictError("example already exists")
            if expected_etag is not None:
                if not getattr(current, "exists", False):
                    raise FaqNotFoundError(record.example_id)
                if int(current.to_dict()["etag"]) != expected_etag:
                    raise FaqVersionConflictError("example was changed by another request")
            transaction.set(record_ref, record.model_dump(mode="python"))
            transaction.set(self._audits.document(audit.audit_id), audit.model_dump(mode="python"))
            if idem_ref is not None:
                transaction.set(
                    idem_ref,
                    {
                        "action": action,
                        "request_fingerprint": request_fingerprint,
                        "result": result,
                    },
                )
            return deepcopy(result)

        return self._run_transaction(operation)

    def purge_expired(
        self,
        *,
        now: datetime,
        retention_days: int = 365,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        cutoff = now - timedelta(days=retention_days)
        removed_ids: list[str] = []
        for doc in self._examples.stream():
            data = doc.to_dict()
            status = data.get("status")
            if status in ("RETIRED", "REJECTED"):
                ret_val = data.get("retired_at") or data.get("updated_at")
                if ret_val:
                    ret_dt = (
                        datetime.fromisoformat(ret_val)
                        if isinstance(ret_val, str)
                        else ret_val
                    )
                    if ret_dt < cutoff:
                        removed_ids.append(doc.id)
                        doc.reference.delete()
        if removed_ids:
            audit = ExampleAuditEvent(
                audit_id=str(uuid.uuid4()),
                example_id="RETENTION_PURGE",
                action="EXAMPLE_RETENTION_PURGED",
                actor_id=actor.user_id if actor else "system.retention",
                actor_role=actor.role if actor else "SYSTEM",
                owner_unit_id="ALL",
                before={"purgedCount": len(removed_ids)},
                after={"purgedIds": removed_ids},
                reason=f"Purged {len(removed_ids)} retired/rejected examples past {retention_days} days retention.",
                occurred_at=now,
            )
            self._audits.document(audit.audit_id).set(audit.model_dump(mode="python"))
        return {"removed": len(removed_ids), "removed_ids": removed_ids}


