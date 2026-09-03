from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import MASKING_POLICY_VERSION, mask_text, redact_secrets

from .faq_domain.errors import (
    FaqAuthorizationError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExampleRecord(StrictModel):
    example_id: str
    source_type: Literal["FAQ", "DOCUMENT", "CONVERSATION", "MANUAL"]
    source_id: str
    source_version_id: str | None = None
    source_correlation_id: str | None = None
    owner_unit_id: str
    text: str = Field(min_length=1, max_length=4000)
    expected_issue_type_id: str
    expected_route: Literal["FAQ", "KNOWLEDGE", "TICKET", "HANDOFF"]
    label: Literal["POSITIVE", "NEGATIVE"]
    reason: str | None = None
    status: Literal["DRAFT", "VERIFIED", "REJECTED", "RETIRED"] = "DRAFT"
    etag: int = Field(ge=1)
    dataset_version: str | None = None
    masking_policy_version: str = MASKING_POLICY_VERSION
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    verified_by: str | None = None
    verified_at: datetime | None = None
    retired_by: str | None = None
    retired_at: datetime | None = None


class ExampleAuditEvent(StrictModel):
    audit_id: str
    example_id: str
    action: str
    actor_id: str
    actor_role: str
    owner_unit_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    occurred_at: datetime
    correlation_id: str | None = None


class ExampleIdempotencyRecord(StrictModel):
    key: str
    action: str
    request_fingerprint: str
    result: dict[str, Any]


class ExampleState(StrictModel):
    examples: tuple[ExampleRecord, ...] = ()
    audits: tuple[ExampleAuditEvent, ...] = ()
    idempotency: tuple[ExampleIdempotencyRecord, ...] = ()


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


class ExampleService:
    def __init__(self, repository: ExampleRepository, *, taxonomy: Any) -> None:
        self._repository = repository
        self._taxonomy = taxonomy

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        if not actor.has_capability(capability) or not actor.allows_owner_unit(owner_unit_id):
            raise FaqAuthorizationError("example operation is outside actor capability or scope")

    @staticmethod
    def _fingerprint(actor: ActorContext, payload: dict[str, Any]) -> str:
        value = {"actor_id": actor.user_id, **payload}
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _result(record: ExampleRecord) -> dict[str, Any]:
        return {"example": record.model_dump(mode="json")}

    def list_examples(
        self,
        *,
        actor: ActorContext,
        source_type: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        visible = []
        for record in self._repository.list_examples():
            try:
                self._authorize(actor, "ops.examples.read", record.owner_unit_id)
            except FaqAuthorizationError:
                continue
            if source_type and record.source_type != source_type:
                continue
            if source_id and record.source_id != source_id:
                continue
            if status and record.status != status:
                continue
            visible.append(record.model_dump(mode="json"))
        return visible

    def detail(self, example_id: str, *, actor: ActorContext) -> dict[str, Any]:
        record = self._require(example_id)
        self._authorize(actor, "ops.examples.read", record.owner_unit_id)
        return {
            **self._result(record),
            "audit": [item.model_dump(mode="json") for item in self._repository.list_audit(example_id)],
        }

    def create(
        self,
        *,
        source_type: str,
        source_id: str,
        source_version_id: str | None,
        source_correlation_id: str | None,
        owner_unit_id: str,
        text: str,
        expected_issue_type_id: str,
        expected_route: str,
        label: str,
        reason: str | None,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self._authorize(actor, "ops.examples.write", owner_unit_id)
        self._taxonomy.require_active(expected_issue_type_id)
        masked = mask_text(text)
        if masked.contains_credential:
            raise FaqValidationError("credentials are not allowed in examples")
        masked_reason = mask_text(reason) if reason else None
        if masked_reason and masked_reason.contains_credential:
            raise FaqValidationError("credentials are not allowed in example reasons")
        if label == "NEGATIVE" and not (reason or "").strip():
            raise FaqValidationError("negative examples require a reason")
        now = datetime.now(UTC)
        request = {
            "action": "EXAMPLE_CREATED",
            "source_type": source_type,
            "source_id": source_id,
            "source_version_id": source_version_id,
            "text": masked.text,
            "expected_issue_type_id": expected_issue_type_id,
            "expected_route": expected_route,
            "label": label,
            "reason": reason,
        }
        fingerprint = self._fingerprint(actor, request)
        replay = self._repository.replay(idempotency_key, "EXAMPLE_CREATED", fingerprint)
        if replay is not None:
            return replay
        record = ExampleRecord(
            example_id=str(uuid.uuid4()),
            source_type=source_type,
            source_id=source_id,
            source_version_id=source_version_id,
            source_correlation_id=source_correlation_id,
            owner_unit_id=owner_unit_id,
            text=masked.text,
            expected_issue_type_id=expected_issue_type_id,
            expected_route=expected_route,
            label=label,
            reason=masked_reason.text if masked_reason else None,
            etag=1,
            created_by=actor.user_id,
            created_at=now,
            updated_by=actor.user_id,
            updated_at=now,
        )
        return self._commit(
            record,
            action="EXAMPLE_CREATED",
            actor=actor,
            before=None,
            expected_etag=None,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
        )

    def update(
        self,
        example_id: str,
        *,
        text: str,
        expected_issue_type_id: str,
        expected_route: str,
        label: str,
        reason: str | None,
        expected_etag: int,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        current = self._require(example_id)
        self._authorize(actor, "ops.examples.write", current.owner_unit_id)
        if current.status == "RETIRED":
            raise FaqTransitionError("retired examples cannot be edited")
        self._taxonomy.require_active(expected_issue_type_id)
        masked = mask_text(text)
        if masked.contains_credential:
            raise FaqValidationError("credentials are not allowed in examples")
        masked_reason = mask_text(reason) if reason else None
        if masked_reason and masked_reason.contains_credential:
            raise FaqValidationError("credentials are not allowed in example reasons")
        if label == "NEGATIVE" and not (reason or "").strip():
            raise FaqValidationError("negative examples require a reason")
        fingerprint = self._fingerprint(
            actor,
            {
                "action": "EXAMPLE_UPDATED",
                "example_id": example_id,
                "etag": expected_etag,
                "text": masked.text,
                "expected_issue_type_id": expected_issue_type_id,
                "expected_route": expected_route,
                "label": label,
                "reason": reason,
            },
        )
        replay = self._repository.replay(idempotency_key, "EXAMPLE_UPDATED", fingerprint)
        if replay is not None:
            return replay
        updated = ExampleRecord.model_validate(
            {
                **current.model_dump(mode="python"),
                "text": masked.text,
                "expected_issue_type_id": expected_issue_type_id,
                "expected_route": expected_route,
                "label": label,
                "reason": masked_reason.text if masked_reason else None,
                "status": "DRAFT",
                "etag": expected_etag + 1,
                "dataset_version": None,
                "verified_by": None,
                "verified_at": None,
                "updated_by": actor.user_id,
                "updated_at": datetime.now(UTC),
            },
        )
        return self._commit(
            updated,
            action="EXAMPLE_UPDATED",
            actor=actor,
            before=current,
            expected_etag=expected_etag,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
        )

    def review(
        self,
        example_id: str,
        *,
        approve: bool,
        reason: str,
        expected_etag: int,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        current = self._require(example_id)
        self._authorize(actor, "ops.examples.verify", current.owner_unit_id)
        if current.status not in {"DRAFT", "REJECTED"}:
            raise FaqTransitionError("only draft or rejected examples can be reviewed")
        action = "EXAMPLE_VERIFIED" if approve else "EXAMPLE_REJECTED"
        fingerprint = self._fingerprint(
            actor,
            {"action": action, "example_id": example_id, "etag": expected_etag, "reason": reason},
        )
        replay = self._repository.replay(idempotency_key, action, fingerprint)
        if replay is not None:
            return replay
        now = datetime.now(UTC)
        updated = current.model_copy(
            update={
                "status": "VERIFIED" if approve else "REJECTED",
                "etag": expected_etag + 1,
                "dataset_version": f"dataset-{now.strftime('%Y%m%dT%H%M%SZ')}" if approve else None,
                "verified_by": actor.user_id if approve else None,
                "verified_at": now if approve else None,
                "updated_by": actor.user_id,
                "updated_at": now,
            }
        )
        return self._commit(
            updated,
            action=action,
            actor=actor,
            before=current,
            expected_etag=expected_etag,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
        )

    def retire(
        self,
        example_id: str,
        *,
        reason: str,
        expected_etag: int,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        current = self._require(example_id)
        self._authorize(actor, "ops.examples.retire", current.owner_unit_id)
        if current.status == "RETIRED":
            raise FaqTransitionError("example is already retired")
        fingerprint = self._fingerprint(
            actor,
            {
                "action": "EXAMPLE_RETIRED",
                "example_id": example_id,
                "etag": expected_etag,
                "reason": reason,
            },
        )
        replay = self._repository.replay(idempotency_key, "EXAMPLE_RETIRED", fingerprint)
        if replay is not None:
            return replay
        now = datetime.now(UTC)
        updated = current.model_copy(
            update={
                "status": "RETIRED",
                "etag": expected_etag + 1,
                "retired_by": actor.user_id,
                "retired_at": now,
                "updated_by": actor.user_id,
                "updated_at": now,
            }
        )
        return self._commit(
            updated,
            action="EXAMPLE_RETIRED",
            actor=actor,
            before=current,
            expected_etag=expected_etag,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
        )

    def _require(self, example_id: str) -> ExampleRecord:
        record = self._repository.get(example_id)
        if record is None:
            raise FaqNotFoundError(example_id)
        return record

    def _commit(
        self,
        record: ExampleRecord,
        *,
        action: str,
        actor: ActorContext,
        before: ExampleRecord | None,
        expected_etag: int | None,
        reason: str | None,
        idempotency_key: str | None,
        request_fingerprint: str,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        result = self._result(record)
        audit = ExampleAuditEvent(
            audit_id=str(uuid.uuid4()),
            example_id=record.example_id,
            action=action,
            actor_id=actor.user_id,
            actor_role=actor.role,
            owner_unit_id=record.owner_unit_id,
            before=redact_secrets(before.model_dump(mode="json")) if before else None,
            after=redact_secrets(record.model_dump(mode="json")),
            reason=mask_text(reason).text if reason else None,
            occurred_at=datetime.now(UTC),
            correlation_id=correlation_id,
        )
        return self._repository.commit(
            record,
            audit,
            expected_etag=expected_etag,
            idempotency_key=idempotency_key,
            action=action,
            request_fingerprint=request_fingerprint,
            result=result,
        )