from __future__ import annotations

import copy
import fcntl
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Protocol

from .errors import EvaluationIdempotencyConflictError
from .models import (
    CandidateGenerationJob,
    CaseRevision,
    EvalCase,
    EvalSet,
    EvalSetVersion,
    EvaluationAuditEvent,
    EvaluationIdempotencyRecord,
    EvaluationState,
)


class EvaluationRepository(Protocol):
    def load(self) -> EvaluationState: ...

    def get_case(self, case_id: str) -> EvalCase | None: ...

    def list_cases(self) -> list[EvalCase]: ...

    def get_revision(self, revision_id: str) -> CaseRevision | None: ...

    def list_revisions_for_case(self, case_id: str) -> list[CaseRevision]: ...

    def get_set(self, set_id: str) -> EvalSet | None: ...

    def list_sets(self) -> list[EvalSet]: ...

    def get_set_version(self, set_version_id: str) -> EvalSetVersion | None: ...

    def list_set_versions(self, set_id: str) -> list[EvalSetVersion]: ...

    def get_candidate_job(self, job_id: str) -> CandidateGenerationJob | None: ...

    def list_candidate_jobs(self) -> list[CandidateGenerationJob]: ...

    def list_audit(self, entity_id: str | None = None) -> list[EvaluationAuditEvent]: ...

    def replay_idempotency(
        self, key: str | None, action: str, fingerprint: str
    ) -> dict[str, Any] | None: ...

    def commit_mutation(
        self,
        new_state: EvaluationState,
        audit: EvaluationAuditEvent | None = None,
        idempotency_record: EvaluationIdempotencyRecord | None = None,
    ) -> None: ...


class InMemoryEvaluationRepository:
    def __init__(self, initial_state: EvaluationState | None = None) -> None:
        self._state = initial_state or EvaluationState()
        self._lock = threading.RLock()

    def load(self) -> EvaluationState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def _save(self, state: EvaluationState) -> None:
        self._state = state

    def get_case(self, case_id: str) -> EvalCase | None:
        with self._lock:
            return next((c for c in self._state.cases if c.case_id == case_id), None)

    def list_cases(self) -> list[EvalCase]:
        with self._lock:
            return sorted(self._state.cases, key=lambda c: c.updated_at, reverse=True)

    def get_revision(self, revision_id: str) -> CaseRevision | None:
        with self._lock:
            return next((r for r in self._state.revisions if r.revision_id == revision_id), None)

    def list_revisions_for_case(self, case_id: str) -> list[CaseRevision]:
        with self._lock:
            return sorted(
                [r for r in self._state.revisions if r.case_id == case_id],
                key=lambda r: r.revision_number,
                reverse=True,
            )

    def get_set(self, set_id: str) -> EvalSet | None:
        with self._lock:
            return next((s for s in self._state.sets if s.set_id == set_id), None)

    def list_sets(self) -> list[EvalSet]:
        with self._lock:
            return sorted(self._state.sets, key=lambda s: s.updated_at, reverse=True)

    def get_set_version(self, set_version_id: str) -> EvalSetVersion | None:
        with self._lock:
            return next((v for v in self._state.set_versions if v.set_version_id == set_version_id), None)

    def list_set_versions(self, set_id: str) -> list[EvalSetVersion]:
        with self._lock:
            return sorted(
                [v for v in self._state.set_versions if v.set_id == set_id],
                key=lambda v: v.version,
                reverse=True,
            )

    def get_candidate_job(self, job_id: str) -> CandidateGenerationJob | None:
        with self._lock:
            return next((j for j in self._state.candidate_jobs if j.job_id == job_id), None)

    def list_candidate_jobs(self) -> list[CandidateGenerationJob]:
        with self._lock:
            return sorted(self._state.candidate_jobs, key=lambda j: j.created_at, reverse=True)

    def list_audit(self, entity_id: str | None = None) -> list[EvaluationAuditEvent]:
        with self._lock:
            if entity_id is None:
                return list(self._state.audits)
            return [a for a in self._state.audits if a.entity_id == entity_id]

    def replay_idempotency(
        self, key: str | None, action: str, fingerprint: str
    ) -> dict[str, Any] | None:
        if not key:
            return None
        with self._lock:
            rec = next((item for item in self._state.idempotency if item.key == key), None)
            if rec is None:
                return None
            if rec.action != action or rec.request_fingerprint != fingerprint:
                raise EvaluationIdempotencyConflictError(
                    "Idempotency key reused with different arguments"
                )
            return copy.deepcopy(rec.result)

    def commit_mutation(
        self,
        new_state: EvaluationState,
        audit: EvaluationAuditEvent | None = None,
        idempotency_record: EvaluationIdempotencyRecord | None = None,
    ) -> None:
        with self._lock:
            audits = list(new_state.audits)
            if audit:
                audits.append(audit)
            idempotency = list(new_state.idempotency)
            if idempotency_record:
                idempotency = [r for r in idempotency if r.key != idempotency_record.key]
                idempotency.append(idempotency_record)
            updated = new_state.model_copy(
                update={"audits": tuple(audits), "idempotency": tuple(idempotency)}
            )
            self._save(updated)


class FileEvaluationRepository(InMemoryEvaluationRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")
        if self._path.exists():
            self._state = self._read_file()

    def _read_file(self) -> EvaluationState:
        if not self._path.exists():
            return EvaluationState()
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return EvaluationState()
        return EvaluationState.model_validate_json(raw)

    def load(self) -> EvaluationState:
        with self._lock:
            self._state = self._read_file()
            return super().load()

    def _save(self, state: EvaluationState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(state.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            directory = os.open(str(self._path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        self._state = state

    def commit_mutation(
        self,
        new_state: EvaluationState,
        audit: EvaluationAuditEvent | None = None,
        idempotency_record: EvaluationIdempotencyRecord | None = None,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                # Reload under lock before committing
                self._state = self._read_file()
                super().commit_mutation(
                    new_state, audit=audit, idempotency_record=idempotency_record
                )
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
