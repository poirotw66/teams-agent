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

from .faq_domain.errors import (
    FaqAuthorizationError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqVersionConflictError,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SyncJob(StrictModel):
    job_id: str
    scope_type: Literal["ALL", "FAQ", "DOCUMENT", "FAILED"]
    scope_ids: tuple[str, ...] = ()
    scope_key: str
    requested_by: str
    owner_unit_id: str
    reason: str
    status: Literal[
        "QUEUED", "VALIDATING", "BUILDING", "VERIFYING", "COMPLETED", "FAILED", "CANCELLED"
    ] = "QUEUED"
    current_stage: str = "QUEUED"
    progress_percent: int = Field(default=0, ge=0, le=100)
    checkpoint_stage: str | None = None
    document_count: int = 0
    warnings: tuple[str, ...] = ()
    error_summary: str | None = None
    correlation_id: str
    target_release: str | None = None
    index_setting_version: str | None = None
    artifact_uri: str | None = None
    retry_of_job_id: str | None = None
    retry_checkpoint_stage: str | None = None
    etag: int = Field(default=1, ge=1)
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SyncAuditEvent(StrictModel):
    audit_id: str
    job_id: str
    action: str
    actor_id: str
    actor_role: str
    owner_unit_id: str
    reason: str | None = None
    occurred_at: datetime


class SyncIdempotency(StrictModel):
    key: str
    actor_id: str
    fingerprint: str
    job_id: str


class SyncState(StrictModel):
    revision: int = 0
    jobs: tuple[SyncJob, ...] = ()
    audits: tuple[SyncAuditEvent, ...] = ()
    idempotency: tuple[SyncIdempotency, ...] = ()


Mutation = Callable[[SyncState], tuple[SyncState, dict[str, Any]]]


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


class SyncService:
    ACTIVE = frozenset({"QUEUED", "VALIDATING", "BUILDING", "VERIFYING"})

    def __init__(self, repository: SyncRepository) -> None:
        self._repository = repository

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        if not actor.has_capability(capability) or not actor.allows_owner_unit(owner_unit_id):
            raise FaqAuthorizationError("sync operation is outside actor capability or scope")

    @staticmethod
    def _audit(job: SyncJob, action: str, actor: ActorContext, reason: str | None = None) -> SyncAuditEvent:
        return SyncAuditEvent(
            audit_id=str(uuid.uuid4()),
            job_id=job.job_id,
            action=action,
            actor_id=actor.user_id,
            actor_role=actor.role,
            owner_unit_id=job.owner_unit_id,
            reason=mask_text(reason).text if reason else None,
            occurred_at=datetime.now(UTC),
        )

    def list_jobs(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        visible = []
        for job in reversed(self._repository.load().jobs):
            try:
                self._authorize(actor, "ops.sync.read", job.owner_unit_id)
            except FaqAuthorizationError:
                continue
            visible.append(job.model_dump(mode="json"))
        return visible

    def detail(self, job_id: str, *, actor: ActorContext) -> dict[str, Any]:
        state = self._repository.load()
        job = next((item for item in state.jobs if item.job_id == job_id), None)
        if job is None:
            raise FaqNotFoundError(job_id)
        self._authorize(actor, "ops.sync.read", job.owner_unit_id)
        return {
            "job": job.model_dump(mode="json"),
            "audit": [item.model_dump(mode="json") for item in state.audits if item.job_id == job_id],
        }

    def create(
        self,
        *,
        scope_type: str,
        scope_ids: tuple[str, ...],
        owner_unit_id: str,
        reason: str,
        actor: ActorContext,
        idempotency_key: str | None,
        correlation_id: str | None,
        retry_of_job_id: str | None = None,
        retry_checkpoint_stage: str | None = None,
    ) -> dict[str, Any]:
        self._authorize(actor, "ops.sync.write", owner_unit_id)
        normalized_ids = tuple(sorted(set(scope_ids)))
        scope_key = f"{scope_type}:{','.join(normalized_ids)}:{owner_unit_id}"
        fingerprint = hashlib.sha256(
            json.dumps(
                {"actor": actor.user_id, "scope": scope_key, "reason": reason},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        def operation(state: SyncState) -> tuple[SyncState, dict[str, Any]]:
            if idempotency_key:
                previous = next((item for item in state.idempotency if item.key == idempotency_key), None)
                if previous:
                    if previous.actor_id != actor.user_id or previous.fingerprint != fingerprint:
                        raise FaqIdempotencyConflictError("sync idempotency key was reused")
                    replay = next(item for item in state.jobs if item.job_id == previous.job_id)
                    return state.model_copy(update={"revision": state.revision + 1}), {
                        "job": replay.model_dump(mode="json")
                    }
            if any(item.scope_key == scope_key and item.status in self.ACTIVE for item in state.jobs):
                raise FaqTransitionError("an active sync job already exists for this scope")
            now = datetime.now(UTC)
            job = SyncJob(
                job_id=str(uuid.uuid4()),
                scope_type=scope_type,
                scope_ids=normalized_ids,
                scope_key=scope_key,
                requested_by=actor.user_id,
                owner_unit_id=owner_unit_id,
                reason=mask_text(reason).text,
                correlation_id=correlation_id or str(uuid.uuid4()),
                retry_of_job_id=retry_of_job_id,
                retry_checkpoint_stage=retry_checkpoint_stage,
                requested_at=now,
            )
            idempotency = state.idempotency
            if idempotency_key:
                idempotency = (
                    *idempotency,
                    SyncIdempotency(
                        key=idempotency_key,
                        actor_id=actor.user_id,
                        fingerprint=fingerprint,
                        job_id=job.job_id,
                    ),
                )
            audit = self._audit(job, "SYNC_REQUESTED", actor, reason)
            next_state = SyncState(
                revision=state.revision + 1,
                jobs=(*state.jobs, job),
                audits=(*state.audits, audit),
                idempotency=idempotency,
            )
            return next_state, {"job": job.model_dump(mode="json")}

        return self._repository.mutate(operation)

    def set_stage(
        self,
        job_id: str,
        *,
        status: Literal["VALIDATING", "BUILDING", "VERIFYING", "COMPLETED", "FAILED"],
        actor: ActorContext,
        document_count: int = 0,
        warnings: tuple[str, ...] = (),
        error_summary: str | None = None,
        target_release: str | None = None,
        index_setting_version: str | None = None,
        artifact_uri: str | None = None,
    ) -> dict[str, Any]:
        allowed = {
            "QUEUED": {"VALIDATING", "FAILED"},
            "VALIDATING": {"BUILDING", "FAILED"},
            "BUILDING": {"VERIFYING", "FAILED"},
            "VERIFYING": {"COMPLETED", "FAILED"},
        }
        progress = {
            "VALIDATING": 20,
            "BUILDING": 60,
            "VERIFYING": 90,
            "COMPLETED": 100,
        }

        def operation(state: SyncState) -> tuple[SyncState, dict[str, Any]]:
            current = next((item for item in state.jobs if item.job_id == job_id), None)
            if current is None:
                raise FaqNotFoundError(job_id)
            if status not in allowed.get(current.status, set()):
                raise FaqTransitionError(f"invalid sync transition: {current.status} -> {status}")
            now = datetime.now(UTC)
            updated = current.model_copy(
                update={
                    "status": status,
                    "current_stage": status,
                    "progress_percent": progress.get(status, current.progress_percent),
                    "checkpoint_stage": (
                        status if status in {"VALIDATING", "BUILDING", "VERIFYING", "COMPLETED"}
                        else current.checkpoint_stage
                    ),
                    "document_count": document_count or current.document_count,
                    "warnings": warnings or current.warnings,
                    "error_summary": mask_text(error_summary).text if error_summary else None,
                    "target_release": target_release or current.target_release,
                    "index_setting_version": index_setting_version or current.index_setting_version,
                    "artifact_uri": artifact_uri or current.artifact_uri,
                    "etag": current.etag + 1,
                    "started_at": current.started_at or now,
                    "finished_at": now if status in {"COMPLETED", "FAILED"} else None,
                }
            )
            jobs = tuple(updated if item.job_id == job_id else item for item in state.jobs)
            audit = self._audit(updated, f"SYNC_{status}", actor, error_summary)
            return SyncState(
                revision=state.revision + 1,
                jobs=jobs,
                audits=(*state.audits, audit),
                idempotency=state.idempotency,
            ), {"job": updated.model_dump(mode="json")}

        return self._repository.mutate(operation)

    def cancel(
        self,
        job_id: str,
        *,
        expected_etag: int,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        def operation(state: SyncState) -> tuple[SyncState, dict[str, Any]]:
            current = next((item for item in state.jobs if item.job_id == job_id), None)
            if current is None:
                raise FaqNotFoundError(job_id)
            self._authorize(actor, "ops.sync.write", current.owner_unit_id)
            if current.etag != expected_etag:
                raise FaqVersionConflictError("sync job was changed by another request")
            if current.status not in self.ACTIVE:
                raise FaqTransitionError("only active sync jobs can be cancelled")
            updated = current.model_copy(
                update={
                    "status": "CANCELLED",
                    "current_stage": "CANCELLED",
                    "error_summary": mask_text(reason).text,
                    "etag": current.etag + 1,
                    "finished_at": datetime.now(UTC),
                }
            )
            jobs = tuple(updated if item.job_id == job_id else item for item in state.jobs)
            audit = self._audit(updated, "SYNC_CANCELLED", actor, reason)
            return SyncState(
                revision=state.revision + 1,
                jobs=jobs,
                audits=(*state.audits, audit),
                idempotency=state.idempotency,
            ), {"job": updated.model_dump(mode="json")}

        return self._repository.mutate(operation)

    def retry(
        self,
        job_id: str,
        *,
        reason: str,
        actor: ActorContext,
        idempotency_key: str | None,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        current = self.detail(job_id, actor=actor)["job"]
        if current["status"] not in {"FAILED", "CANCELLED"}:
            raise FaqTransitionError("only failed or cancelled sync jobs can be retried")
        return self.create(
            scope_type=current["scope_type"],
            scope_ids=tuple(current["scope_ids"]),
            owner_unit_id=current["owner_unit_id"],
            reason=reason,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            retry_of_job_id=job_id,
            retry_checkpoint_stage=current["checkpoint_stage"],
        )