"""File-backed evaluation repository with per-resource record sidecars."""

from __future__ import annotations

import fcntl
import os
import sys
import uuid
from pathlib import Path

from .errors import EvaluationVersionConflictError
from .models import (
    CaseRevision,
    EvalCase,
    EvaluationAuditEvent,
    EvaluationIdempotencyRecord,
    EvaluationState,
)
from .repository import InMemoryEvaluationRepository
from .runner_models import CaseExecution, EvaluationRun


class FileEvaluationRepository(InMemoryEvaluationRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")
        self._records_dir = path.parent / f"{path.stem}_records"
        self._cases_dir = self._records_dir / "cases"
        self._runs_dir = self._records_dir / "runs"
        self._records_dir.mkdir(parents=True, exist_ok=True)
        self._cases_dir.mkdir(parents=True, exist_ok=True)
        self._runs_dir.mkdir(parents=True, exist_ok=True)
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
            if sys.platform != "win32":
                directory = os.open(str(self._path.parent), os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

        # Also write per-resource files for individual records
        for case in state.cases:
            case_file = self._cases_dir / f"{case.case_id}.json"
            case_tmp = case_file.with_suffix(f".{uuid.uuid4().hex}.tmp")
            case_tmp.write_text(case.model_dump_json(indent=2), encoding="utf-8")
            os.replace(case_tmp, case_file)
        for run in state.runs:
            run_file = self._runs_dir / f"{run.run_id}.json"
            run_tmp = run_file.with_suffix(f".{uuid.uuid4().hex}.tmp")
            run_tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
            os.replace(run_tmp, run_file)

        self._state = state

    def commit_mutation(
        self,
        new_state: EvaluationState,
        audit: EvaluationAuditEvent | None = None,
        idempotency_record: EvaluationIdempotencyRecord | None = None,
        expected_revision: int | None = None,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                # Reload under lock before committing
                fresh = self._read_file()
                if expected_revision is not None and hasattr(fresh, "revision"):
                    if fresh.revision != expected_revision:
                        raise EvaluationVersionConflictError(
                            f"Revision conflict: expected {expected_revision}, got {fresh.revision}"
                        )
                self._state = fresh
                super().commit_mutation(
                    new_state,
                    audit=audit,
                    idempotency_record=idempotency_record,
                    expected_revision=expected_revision,
                )
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def get_case(self, case_id: str) -> EvalCase | None:
        case_file = self._cases_dir / f"{case_id}.json"
        if case_file.exists():
            try:
                return EvalCase.model_validate_json(case_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return super().get_case(case_id)

    def get_run(self, run_id: str) -> EvaluationRun | None:
        run_file = self._runs_dir / f"{run_id}.json"
        if run_file.exists():
            try:
                return EvaluationRun.model_validate_json(run_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return super().get_run(run_id)

    def update_case(
        self,
        case: EvalCase,
        revision: CaseRevision | None = None,
        audit: EvaluationAuditEvent | None = None,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                if self._path.exists():
                    self._state = self._read_file()
                super().update_case(case, revision=revision, audit=audit)
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def update_run(
        self,
        run: EvaluationRun,
        executions: list[CaseExecution] | None = None,
        audit: EvaluationAuditEvent | None = None,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                if self._path.exists():
                    self._state = self._read_file()
                super().update_run(run, executions=executions, audit=audit)
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def delete_outbox_jobs(self, outbox_ids: set[str] | list[str]) -> None:
        with open(self._lock_path, "w") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                if self._path.exists():
                    self._state = self._read_file()
                super().delete_outbox_jobs(outbox_ids)
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
