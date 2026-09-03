from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import (
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqVersionConflictError,
)
from .models import FaqAuditEvent, FaqRecord, FaqState, FaqTestCase, FaqVersion, IdempotencyRecord


def fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FaqCommit:
    faq: FaqRecord
    versions: tuple[FaqVersion, ...]
    tests: tuple[FaqTestCase, ...]
    audit: FaqAuditEvent
    expected_etag: int | None
    idempotency_key: str | None
    action: str
    request_fingerprint: str
    result: dict[str, Any]
    active_pointer: tuple[str, str | None] | None = None


class FaqRepository(Protocol):
    def get_faq(self, faq_id: str) -> FaqRecord | None: ...

    def get_faq_by_key(self, faq_key: str) -> FaqRecord | None: ...

    def get_version(self, version_id: str) -> FaqVersion | None: ...

    def list_versions(self, faq_id: str) -> list[FaqVersion]: ...

    def list_tests(self, version_id: str) -> list[FaqTestCase]: ...

    def list_audit(self, faq_id: str) -> list[FaqAuditEvent]: ...

    def get_active_version_id(self, faq_key: str) -> str | None: ...

    def get_active_version(self, faq_key: str) -> FaqVersion | None: ...

    def replay(
        self, *, key: str | None, action: str, request_fingerprint: str
    ) -> dict[str, Any] | None: ...

    def commit(self, commit: FaqCommit) -> dict[str, Any]: ...


class InMemoryFaqRepository:
    """Test-only repository; production construction must select FILE or FIRESTORE."""

    def __init__(self) -> None:
        self._state = FaqState()
        self._lock = threading.RLock()

    def _load_state(self) -> FaqState:
        return self._state.model_copy(deep=True)

    def _save_state(self, state: FaqState) -> None:
        self._state = FaqState.model_validate(state.model_dump(), context={"persisted": True})

    @staticmethod
    def _indexes(state: FaqState):
        return (
            {item.faq_id: item for item in state.faqs},
            {item.faq_key: item for item in state.faqs},
            {item.version_id: item for item in state.versions},
            {item.key: item for item in state.idempotency},
        )

    def get_faq(self, faq_id: str) -> FaqRecord | None:
        with self._lock:
            return self._indexes(self._load_state())[0].get(faq_id)

    def get_faq_by_key(self, faq_key: str) -> FaqRecord | None:
        with self._lock:
            return self._indexes(self._load_state())[1].get(faq_key)

    def get_version(self, version_id: str) -> FaqVersion | None:
        with self._lock:
            return self._indexes(self._load_state())[2].get(version_id)

    def list_versions(self, faq_id: str) -> list[FaqVersion]:
        with self._lock:
            return sorted(
                (item for item in self._load_state().versions if item.faq_id == faq_id),
                key=lambda item: item.version_number,
            )

    def list_tests(self, version_id: str) -> list[FaqTestCase]:
        with self._lock:
            return [item for item in self._load_state().tests if item.version_id == version_id]

    def list_audit(self, faq_id: str) -> list[FaqAuditEvent]:
        with self._lock:
            return [item for item in self._load_state().audits if item.faq_id == faq_id]

    def get_active_version_id(self, faq_key: str) -> str | None:
        with self._lock:
            return self._load_state().active_pointers.get(faq_key)

    def get_active_version(self, faq_key: str) -> FaqVersion | None:
        with self._lock:
            state = self._load_state()
            version_id = state.active_pointers.get(faq_key)
            return self._indexes(state)[2].get(version_id) if version_id else None

    def replay(
        self, *, key: str | None, action: str, request_fingerprint: str
    ) -> dict[str, Any] | None:
        if not key:
            return None
        with self._lock:
            record = self._indexes(self._load_state())[3].get(key)
            if record is None:
                return None
            if record.action != action or record.request_fingerprint != request_fingerprint:
                raise FaqIdempotencyConflictError(
                    "idempotency key was reused with a different request"
                )
            return record.result

    def commit(self, commit: FaqCommit) -> dict[str, Any]:
        commit = deepcopy(commit)
        with self._lock:
            state = self._load_state()
            faqs, keys, _versions, idempotency = self._indexes(state)
            if commit.idempotency_key:
                previous = idempotency.get(commit.idempotency_key)
                if previous:
                    if (
                        previous.action != commit.action
                        or previous.request_fingerprint != commit.request_fingerprint
                    ):
                        raise FaqIdempotencyConflictError(
                            "idempotency key was reused with a different request"
                        )
                    return previous.result
            current = faqs.get(commit.faq.faq_id)
            if commit.expected_etag is None:
                if current is not None or (
                    commit.faq.faq_key in keys
                    and keys[commit.faq.faq_key].faq_id != commit.faq.faq_id
                ):
                    raise FaqVersionConflictError("faqId or faqKey already exists")
            elif current is None:
                raise FaqNotFoundError(commit.faq.faq_id)
            elif current.etag != commit.expected_etag:
                raise FaqVersionConflictError("FAQ was changed by another request")
            _validate_commit(commit, current, _versions)

            next_faqs = [item for item in state.faqs if item.faq_id != commit.faq.faq_id]
            next_faqs.append(commit.faq)
            version_ids = {item.version_id for item in commit.versions}
            next_versions = [item for item in state.versions if item.version_id not in version_ids]
            next_versions.extend(commit.versions)
            test_ids = {item.test_case_id for item in commit.tests}
            next_tests = [item for item in state.tests if item.test_case_id not in test_ids]
            next_tests.extend(commit.tests)
            pointers = dict(state.active_pointers)
            if commit.active_pointer:
                key, version_id = commit.active_pointer
                if version_id is None:
                    pointers.pop(key, None)
                else:
                    pointers[key] = version_id
            next_idempotency = list(state.idempotency)
            if commit.idempotency_key:
                next_idempotency.append(
                    IdempotencyRecord(
                        key=commit.idempotency_key,
                        action=commit.action,
                        request_fingerprint=commit.request_fingerprint,
                        result=commit.result,
                        created_at=commit.audit.occurred_at,
                    )
                )
            next_state = FaqState.model_validate(
                dict(
                    faqs=tuple(next_faqs), versions=tuple(next_versions),
                    tests=tuple(next_tests), audits=(*state.audits, commit.audit),
                    idempotency=tuple(next_idempotency), active_pointers=pointers,
                ),
                context={"persisted": True},
            )
            # The state and its audit record only become visible together.
            self._save_state(next_state)
            return deepcopy(commit.result)


class FileFaqRepository(InMemoryFaqRepository):
    """Local persistent repository with an OS-level writer lock and atomic replace."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")

    def _read_file(self) -> FaqState:
        if not self._path.exists():
            return FaqState()
        return FaqState.model_validate_json(
            self._path.read_text(encoding="utf-8"), context={"persisted": True}
        )

    def _load_state(self) -> FaqState:
        return self._read_file()

    def _save_state(self, state: FaqState) -> None:
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

    def commit(self, commit: FaqCommit) -> dict[str, Any]:
        # fcntl is intentionally local-only: FILE mode is a local bootstrap backend,
        # while multi-host production must use the Firestore transaction implementation.
        import fcntl

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                return super().commit(commit)
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


class FirestoreFaqRepository:
    """Firestore repository. Each command writes state and its domain audit atomically.

    The supplied client is deliberately injectable for local fake-client tests. This
    class does not create a client, read ADC, or contact Google during construction.
    """

    def __init__(
        self, client: Any, *, collection_prefix: str = "ai_ops_faq",
        transaction_runner: Any = None,
    ) -> None:
        self._client = client
        self._transaction_runner = transaction_runner
        self._faqs = client.collection(f"{collection_prefix}_faqs")
        self._versions = client.collection(f"{collection_prefix}_versions")
        self._tests = client.collection(f"{collection_prefix}_tests")
        self._audits = client.collection(f"{collection_prefix}_audit")
        self._idem = client.collection(f"{collection_prefix}_idempotency")
        self._keys = client.collection(f"{collection_prefix}_keys")
        self._pointers = client.collection(f"{collection_prefix}_active")

    @staticmethod
    def _as(model: Any) -> dict[str, Any]:
        return model.model_dump(mode="python")

    def _read(self, ref: Any) -> dict[str, Any] | None:
        snapshot = ref.get()
        if not getattr(snapshot, "exists", False):
            return None
        return snapshot.to_dict()

    def get_faq(self, faq_id: str) -> FaqRecord | None:
        payload = self._read(self._faqs.document(faq_id))
        return FaqRecord.model_validate(payload) if payload else None

    def get_faq_by_key(self, faq_key: str) -> FaqRecord | None:
        key = self._read(self._keys.document(faq_key))
        return self.get_faq(str(key["faq_id"])) if key else None

    def get_version(self, version_id: str) -> FaqVersion | None:
        payload = self._read(self._versions.document(version_id))
        return FaqVersion.model_validate(payload) if payload else None

    def _where(self, collection: Any, field: str, value: str, model: Any) -> list[Any]:
        return [
            model.model_validate(item.to_dict(), context={"persisted": True})
            for item in collection.where(field, "==", value).stream()
        ]

    def list_versions(self, faq_id: str) -> list[FaqVersion]:
        return sorted(
            self._where(self._versions, "faq_id", faq_id, FaqVersion),
            key=lambda item: item.version_number,
        )

    def list_tests(self, version_id: str) -> list[FaqTestCase]:
        return self._where(self._tests, "version_id", version_id, FaqTestCase)

    def list_audit(self, faq_id: str) -> list[FaqAuditEvent]:
        return self._where(self._audits, "faq_id", faq_id, FaqAuditEvent)

    def get_active_version_id(self, faq_key: str) -> str | None:
        payload = self._read(self._pointers.document(faq_key))
        return str(payload["version_id"]) if payload and payload.get("version_id") else None

    def _run_transaction(self, operation: Any) -> Any:
        """Run after the SDK has begun the transaction, including SDK retries."""
        if self._transaction_runner is not None:
            return self._transaction_runner(operation, self._client.transaction())
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:  # pragma: no cover - optional dependency guard
            raise RuntimeError("FIRESTORE FAQ repository requires google-cloud-firestore") from error
        return transactional(operation)(self._client.transaction())

    def get_active_version(self, faq_key: str) -> FaqVersion | None:
        pointer_ref = self._pointers.document(faq_key)

        def operation(transaction: Any) -> FaqVersion | None:
            pointer = pointer_ref.get(transaction=transaction)
            if not getattr(pointer, "exists", False):
                return None
            version_id = pointer.to_dict().get("version_id")
            if version_id is None:
                return None
            version = self._versions.document(str(version_id)).get(
                transaction=transaction
            )
            return (
                FaqVersion.model_validate(version.to_dict())
                if getattr(version, "exists", False)
                else None
            )

        return self._run_transaction(operation)

    def replay(
        self, *, key: str | None, action: str, request_fingerprint: str
    ) -> dict[str, Any] | None:
        if not key:
            return None
        payload = self._read(self._idem.document(key))
        if payload is None:
            return None
        if payload["action"] != action or payload["request_fingerprint"] != request_fingerprint:
            raise FaqIdempotencyConflictError("idempotency key was reused with a different request")
        return deepcopy(payload["result"])

    def commit(self, commit: FaqCommit) -> dict[str, Any]:
        commit = deepcopy(commit)
        faq_ref = self._faqs.document(commit.faq.faq_id)
        key_ref = self._keys.document(commit.faq.faq_key)
        idem_ref = self._idem.document(commit.idempotency_key) if commit.idempotency_key else None

        def operation(transaction: Any) -> dict[str, Any]:
            current = faq_ref.get(transaction=transaction)
            existing_key = key_ref.get(transaction=transaction)
            if idem_ref is not None:
                previous = idem_ref.get(transaction=transaction)
                if getattr(previous, "exists", False):
                    data = previous.to_dict()
                    if (
                        data["action"] != commit.action
                        or data["request_fingerprint"] != commit.request_fingerprint
                    ):
                        raise FaqIdempotencyConflictError(
                            "idempotency key was reused with a different request"
                        )
                    return deepcopy(data["result"])
            if commit.expected_etag is None:
                if getattr(current, "exists", False) or getattr(existing_key, "exists", False):
                    raise FaqVersionConflictError("faqId or faqKey already exists")
            else:
                if not getattr(current, "exists", False):
                    raise FaqNotFoundError(commit.faq.faq_id)
                if int(current.to_dict()["etag"]) != commit.expected_etag:
                    raise FaqVersionConflictError("FAQ was changed by another request")
            existing_versions = {}
            for version in commit.versions:
                snapshot = self._versions.document(version.version_id).get(transaction=transaction)
                if snapshot.exists:
                    existing_versions[version.version_id] = FaqVersion.model_validate(snapshot.to_dict())
            _validate_commit(
                commit,
                FaqRecord.model_validate(current.to_dict()) if current.exists else None,
                existing_versions,
            )
            transaction.set(faq_ref, self._as(commit.faq))
            transaction.set(key_ref, {"faq_id": commit.faq.faq_id})
            for version in commit.versions:
                transaction.set(self._versions.document(version.version_id), self._as(version))
            for test in commit.tests:
                transaction.set(self._tests.document(test.test_case_id), self._as(test))
            transaction.set(self._audits.document(commit.audit.audit_id), self._as(commit.audit))
            if commit.active_pointer:
                key, version_id = commit.active_pointer
                transaction.set(self._pointers.document(key), {"version_id": version_id})
            if idem_ref is not None:
                transaction.set(
                    idem_ref,
                    {
                        "action": commit.action,
                        "request_fingerprint": commit.request_fingerprint,
                        "result": commit.result,
                    },
                )
            return deepcopy(commit.result)

        return self._run_transaction(operation)


def _validate_commit(
    commit: FaqCommit, current: FaqRecord | None, versions: dict[str, FaqVersion],
) -> None:
    """Reject stale-derived etags and attempts to overwrite immutable content."""
    if commit.faq.etag != (commit.expected_etag or 0) + 1:
        raise FaqVersionConflictError("next etag must increment the compared etag")
    if current and current.faq_key != commit.faq.faq_key:
        raise FaqVersionConflictError("faqKey is immutable")
    if commit.audit.faq_id != commit.faq.faq_id or commit.audit.action != commit.action:
        raise FaqVersionConflictError("audit does not describe the committed FAQ operation")
    for version in commit.versions:
        if version.faq_id != commit.faq.faq_id:
            raise FaqVersionConflictError("version belongs to another FAQ")
        previous = versions.get(version.version_id)
        if previous and any(
            getattr(previous, field) != getattr(version, field)
            for field in ("faq_id", "version_number", "content", "created_at", "created_by")
        ):
            raise FaqVersionConflictError("version content is immutable; create a new draft")
