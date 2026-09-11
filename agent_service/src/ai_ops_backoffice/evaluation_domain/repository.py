from __future__ import annotations

import copy
import fcntl
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Protocol

from .errors import (
    EvaluationIdempotencyConflictError,
    EvaluationVersionConflictError,
)
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
from .runner_models import CaseExecution, EvaluationRun, ReviewDecision


class EvaluationRepository(Protocol):
    def load(self) -> EvaluationState: ...

    def get_case(self, case_id: str) -> EvalCase | None: ...

    def list_cases(self, tenant_id: str | None = None) -> list[EvalCase]: ...

    def get_revision(self, revision_id: str) -> CaseRevision | None: ...

    def list_revisions_for_case(self, case_id: str) -> list[CaseRevision]: ...

    def get_set(self, set_id: str) -> EvalSet | None: ...

    def list_sets(self, tenant_id: str | None = None) -> list[EvalSet]: ...

    def get_set_version(self, set_version_id: str) -> EvalSetVersion | None: ...

    def list_set_versions(self, set_id: str) -> list[EvalSetVersion]: ...

    def get_candidate_job(self, job_id: str) -> CandidateGenerationJob | None: ...

    def list_candidate_jobs(self) -> list[CandidateGenerationJob]: ...

    def get_run(self, run_id: str) -> EvaluationRun | None: ...

    def list_runs(
        self, set_version_id: str | None = None, tenant_id: str | None = None
    ) -> list[EvaluationRun]: ...

    def get_case_execution(self, execution_id: str) -> CaseExecution | None: ...

    def list_case_executions(
        self, run_id: str, target_side: str | None = None
    ) -> list[CaseExecution]: ...

    def list_review_decisions(
        self, run_id: str | None = None
    ) -> list[ReviewDecision]: ...

    def list_audit(self, entity_id: str | None = None) -> list[EvaluationAuditEvent]: ...

    def replay_idempotency(
        self, key: str | None, action: str, fingerprint: str
    ) -> dict[str, Any] | None: ...

    def commit_mutation(
        self,
        new_state: EvaluationState,
        audit: EvaluationAuditEvent | None = None,
        idempotency_record: EvaluationIdempotencyRecord | None = None,
        expected_revision: int | None = None,
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

    def list_cases(self, tenant_id: str | None = None) -> list[EvalCase]:
        with self._lock:
            cases = self._state.cases
            if tenant_id:
                cases = tuple(c for c in cases if c.tenant_id == tenant_id)
            return sorted(cases, key=lambda c: c.updated_at, reverse=True)

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

    def list_sets(self, tenant_id: str | None = None) -> list[EvalSet]:
        with self._lock:
            sets = self._state.sets
            if tenant_id:
                sets = tuple(s for s in sets if s.tenant_id == tenant_id)
            return sorted(sets, key=lambda s: s.updated_at, reverse=True)

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

    def get_run(self, run_id: str) -> EvaluationRun | None:
        with self._lock:
            return next((r for r in self._state.runs if r.run_id == run_id), None)

    def list_runs(
        self, set_version_id: str | None = None, tenant_id: str | None = None
    ) -> list[EvaluationRun]:
        with self._lock:
            runs = self._state.runs
            if set_version_id:
                runs = tuple(r for r in runs if r.set_version_id == set_version_id)
            if tenant_id:
                runs = tuple(r for r in runs if r.tenant_id == tenant_id)
            return sorted(runs, key=lambda r: r.created_at, reverse=True)

    def get_case_execution(self, execution_id: str) -> CaseExecution | None:
        with self._lock:
            return next(
                (e for e in self._state.case_executions if e.execution_id == execution_id), None
            )

    def list_case_executions(
        self, run_id: str, target_side: str | None = None
    ) -> list[CaseExecution]:
        with self._lock:
            executions = [e for e in self._state.case_executions if e.run_id == run_id]
            if target_side:
                executions = [e for e in executions if e.target_side == target_side]
            return executions

    def list_review_decisions(
        self, run_id: str | None = None
    ) -> list[ReviewDecision]:
        with self._lock:
            if run_id:
                return [d for d in self._state.review_decisions if d.run_id == run_id]
            return list(self._state.review_decisions)

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
        expected_revision: int | None = None,
    ) -> None:
        with self._lock:
            if expected_revision is not None and hasattr(self._state, "revision"):
                if self._state.revision != expected_revision:
                    raise EvaluationVersionConflictError(
                        f"Revision conflict: expected {expected_revision}, got {self._state.revision}"
                    )
            audits = list(new_state.audits)
            if audit:
                audits.append(audit)
            idempotency = list(new_state.idempotency)
            if idempotency_record:
                idempotency = [r for r in idempotency if r.key != idempotency_record.key]
                idempotency.append(idempotency_record)
            next_revision = self._state.revision + 1 if hasattr(self._state, "revision") else 1
            updated = new_state.model_copy(
                update={
                    "audits": tuple(audits),
                    "idempotency": tuple(idempotency),
                    "revision": next_revision,
                }
            )
            self._save(updated)


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
            directory = os.open(str(self._path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

        # Also write per-resource files for individual records
        for c in state.cases:
            case_file = self._cases_dir / f"{c.case_id}.json"
            case_tmp = case_file.with_suffix(f".{uuid.uuid4().hex}.tmp")
            case_tmp.write_text(c.model_dump_json(indent=2), encoding="utf-8")
            os.replace(case_tmp, case_file)
        for r in state.runs:
            run_file = self._runs_dir / f"{r.run_id}.json"
            run_tmp = run_file.with_suffix(f".{uuid.uuid4().hex}.tmp")
            run_tmp.write_text(r.model_dump_json(indent=2), encoding="utf-8")
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
                    if getattr(fresh, "revision") != expected_revision:
                        raise EvaluationVersionConflictError(
                            f"Revision conflict: expected {expected_revision}, got {getattr(fresh, 'revision')}"
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


class FirestoreEvaluationRepository(InMemoryEvaluationRepository):
    """Production GCP Firestore repository for evaluations with tenant isolation and CAS."""

    def __init__(
        self,
        client: Any,
        collection_prefix: str = "ai_ops_eval",
        transaction_runner: Any = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._prefix = collection_prefix
        self._transaction_runner = transaction_runner

    def _col(self, name: str) -> Any:
        return self._client.collection(f"{self._prefix}_{name}")

    def _run_transaction(self, operation: Any) -> Any:
        if self._transaction_runner is not None:
            tx = self._client.transaction() if hasattr(self._client, "transaction") else None
            return self._transaction_runner(operation, tx)
        if hasattr(self._client, "transaction"):
            try:
                from google.cloud.firestore_v1.transaction import transactional
                return transactional(operation)(self._client.transaction())
            except (ImportError, Exception):
                tx = self._client.transaction()
                res = operation(tx)
                if hasattr(tx, "commit"):
                    tx.commit()
                return res
        class _ImmediateTx:
            def get(self, ref: Any) -> Any:
                return ref.get()
            def set(self, ref: Any, data: Any, merge: bool = False) -> None:
                ref.set(data, merge=merge) if hasattr(ref, "set") else None
            def update(self, ref: Any, data: Any) -> None:
                ref.update(data) if hasattr(ref, "update") else (ref.set(data) if hasattr(ref, "set") else None)
        return operation(_ImmediateTx())

    def load(self) -> EvaluationState:
        meta_ref = self._col("meta").document("root")
        meta_snap = meta_ref.get() if hasattr(meta_ref, "get") else None
        current_rev = meta_snap.to_dict().get("revision", 1) if (meta_snap and getattr(meta_snap, "exists", False)) else 1

        cases = [EvalCase.model_validate(d.to_dict()) for d in self._col("cases").stream()]
        revisions = [CaseRevision.model_validate(d.to_dict()) for d in self._col("revisions").stream()]
        sets = [EvalSet.model_validate(d.to_dict()) for d in self._col("sets").stream()]
        set_versions = [EvalSetVersion.model_validate(d.to_dict()) for d in self._col("set_versions").stream()]
        candidate_jobs = [CandidateGenerationJob.model_validate(d.to_dict()) for d in self._col("candidate_jobs").stream()]
        runs = [EvaluationRun.model_validate(d.to_dict()) for d in self._col("runs").stream()]
        case_executions = [CaseExecution.model_validate(d.to_dict()) for d in self._col("executions").stream()]
        review_decisions = [ReviewDecision.model_validate(d.to_dict()) for d in self._col("reviews").stream()]
        audits = [EvaluationAuditEvent.model_validate(d.to_dict()) for d in self._col("audits").stream()]
        idempotency = [EvaluationIdempotencyRecord.model_validate(d.to_dict()) for d in self._col("idempotency").stream()]

        loaded = EvaluationState(
            revision=current_rev,
            cases=tuple(cases),
            revisions=tuple(revisions),
            sets=tuple(sets),
            set_versions=tuple(set_versions),
            candidate_jobs=tuple(candidate_jobs),
            runs=tuple(runs),
            case_executions=tuple(case_executions),
            review_decisions=tuple(review_decisions),
            audits=tuple(audits),
            idempotency=tuple(idempotency),
        )
        with self._lock:
            self._state = loaded
        return loaded

    def commit_mutation(
        self,
        new_state: EvaluationState,
        audit: EvaluationAuditEvent | None = None,
        idempotency_record: EvaluationIdempotencyRecord | None = None,
        expected_revision: int | None = None,
    ) -> None:
        import json
        meta_ref = self._col("meta").document("root")

        def op(transaction: Any) -> int:
            meta_snap = meta_ref.get(transaction=transaction) if hasattr(meta_ref, "get") else None
            curr_rev = meta_snap.to_dict().get("revision", 1) if (meta_snap and getattr(meta_snap, "exists", False)) else 1
            if expected_revision is not None and curr_rev != expected_revision:
                raise EvaluationVersionConflictError(
                    f"Revision conflict: expected {expected_revision}, got {curr_rev}"
                )
            next_rev = curr_rev + 1
            transaction.set(meta_ref, {"revision": next_rev})

            for c in new_state.cases:
                ref = self._col("cases").document(c.case_id)
                transaction.set(ref, json.loads(c.model_dump_json()))
            for r in new_state.revisions:
                ref = self._col("revisions").document(r.revision_id)
                transaction.set(ref, json.loads(r.model_dump_json()))
            for s in new_state.sets:
                ref = self._col("sets").document(s.set_id)
                transaction.set(ref, json.loads(s.model_dump_json()))
            for sv in new_state.set_versions:
                ref = self._col("set_versions").document(sv.set_version_id)
                transaction.set(ref, json.loads(sv.model_dump_json()))
            for j in new_state.candidate_jobs:
                ref = self._col("candidate_jobs").document(j.job_id)
                transaction.set(ref, json.loads(j.model_dump_json()))
            for run in new_state.runs:
                ref = self._col("runs").document(run.run_id)
                transaction.set(ref, json.loads(run.model_dump_json()))
            for ex in new_state.case_executions:
                ref = self._col("executions").document(ex.execution_id)
                transaction.set(ref, json.loads(ex.model_dump_json()))
            for rev in new_state.review_decisions:
                ref = self._col("reviews").document(rev.decision_id)
                transaction.set(ref, json.loads(rev.model_dump_json()))

            if audit:
                ref = self._col("audits").document(audit.audit_id)
                transaction.set(ref, json.loads(audit.model_dump_json()))
            if idempotency_record:
                ref = self._col("idempotency").document(idempotency_record.key)
                transaction.set(ref, json.loads(idempotency_record.model_dump_json()))
            return next_rev

        next_rev = self._run_transaction(op)
        with self._lock:
            audits = list(new_state.audits)
            if audit:
                audits.append(audit)
            idempotency = list(new_state.idempotency)
            if idempotency_record:
                idempotency = [r for r in idempotency if r.key != idempotency_record.key]
                idempotency.append(idempotency_record)
            self._state = new_state.model_copy(
                update={
                    "revision": next_rev,
                    "audits": tuple(audits),
                    "idempotency": tuple(idempotency),
                }
            )

