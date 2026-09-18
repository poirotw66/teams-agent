"""Evaluation repository port and in-memory implementation.

File and Firestore adapters live in dedicated modules and are re-exported here
so existing ``from .repository import ...`` imports keep working.
"""

from __future__ import annotations

import copy
import threading
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

    def update_case(
        self,
        case: EvalCase,
        revision: CaseRevision | None = None,
        audit: EvaluationAuditEvent | None = None,
    ) -> None: ...

    def update_run(
        self,
        run: EvaluationRun,
        executions: list[CaseExecution] | None = None,
        audit: EvaluationAuditEvent | None = None,
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
            return next(
                (v for v in self._state.set_versions if v.set_version_id == set_version_id),
                None,
            )

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

    def delete_outbox_jobs(self, outbox_ids: set[str] | list[str]) -> None:
        target_ids = {str(i) for i in outbox_ids}
        with self._lock:
            remaining = [
                j
                for j in getattr(self._state, "outbox_jobs", ())
                if str(j.get("outbox_id", j.get("job_id"))) not in target_ids
            ]
            next_revision = self._state.revision + 1 if hasattr(self._state, "revision") else 1
            self._state = self._state.model_copy(
                update={"outbox_jobs": tuple(remaining), "revision": next_revision}
            )
            self._save(self._state)

    def update_case(
        self,
        case: EvalCase,
        revision: CaseRevision | None = None,
        audit: EvaluationAuditEvent | None = None,
    ) -> None:
        with self._lock:
            cases = [c for c in self._state.cases if c.case_id != case.case_id] + [case]
            revisions = list(self._state.revisions)
            if revision and not any(r.revision_id == revision.revision_id for r in revisions):
                revisions.append(revision)
            audits = list(self._state.audits)
            if audit:
                audits.append(audit)
            next_rev = self._state.revision + 1 if hasattr(self._state, "revision") else 1
            new_state = self._state.model_copy(
                update={
                    "cases": tuple(cases),
                    "revisions": tuple(revisions),
                    "audits": tuple(audits),
                    "revision": next_rev,
                }
            )
            self._save(new_state)

    def update_run(
        self,
        run: EvaluationRun,
        executions: list[CaseExecution] | None = None,
        audit: EvaluationAuditEvent | None = None,
    ) -> None:
        with self._lock:
            runs = [r for r in self._state.runs if r.run_id != run.run_id] + [run]
            case_execs = list(self._state.case_executions)
            if executions:
                exec_ids = {e.execution_id for e in executions}
                case_execs = [e for e in case_execs if e.execution_id not in exec_ids] + executions
            audits = list(self._state.audits)
            if audit:
                audits.append(audit)
            next_rev = self._state.revision + 1 if hasattr(self._state, "revision") else 1
            new_state = self._state.model_copy(
                update={
                    "runs": tuple(runs),
                    "case_executions": tuple(case_execs),
                    "audits": tuple(audits),
                    "revision": next_rev,
                }
            )
            self._save(new_state)


from .file_evaluation_repository import FileEvaluationRepository
from .firestore_evaluation_repository import FirestoreEvaluationRepository

__all__ = [
    "EvaluationRepository",
    "FileEvaluationRepository",
    "FirestoreEvaluationRepository",
    "InMemoryEvaluationRepository",
]
