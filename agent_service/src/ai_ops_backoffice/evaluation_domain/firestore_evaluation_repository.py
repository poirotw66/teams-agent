"""Firestore-backed evaluation repository with tenant isolation and CAS."""

from __future__ import annotations

from typing import Any

from .errors import EvaluationVersionConflictError
from .firestore_evaluation_helpers import (
    apply_evaluation_state_diff,
    compute_evaluation_state_diff,
    model_document_payload,
    outbox_key,
    read_meta_revision,
    run_client_transaction,
    strip_revision_metadata,
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
from .repository import InMemoryEvaluationRepository
from .runner_models import CaseExecution, EvaluationRun, ReviewDecision


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
        return run_client_transaction(
            self._client, operation, transaction_runner=self._transaction_runner
        )

    def load(self) -> EvaluationState:
        current_rev = read_meta_revision(self._col("meta").document("root"))

        def _clean(doc: Any) -> dict[str, Any]:
            return strip_revision_metadata(dict(doc.to_dict() or {}))

        cases = [EvalCase.model_validate(_clean(d)) for d in self._col("cases").stream()]
        revisions = [
            CaseRevision.model_validate(_clean(d)) for d in self._col("revisions").stream()
        ]
        sets = [EvalSet.model_validate(_clean(d)) for d in self._col("sets").stream()]
        set_versions = [
            EvalSetVersion.model_validate(_clean(d)) for d in self._col("set_versions").stream()
        ]
        candidate_jobs = [
            CandidateGenerationJob.model_validate(_clean(d))
            for d in self._col("candidate_jobs").stream()
        ]
        runs = [EvaluationRun.model_validate(_clean(d)) for d in self._col("runs").stream()]
        case_executions = [
            CaseExecution.model_validate(_clean(d)) for d in self._col("executions").stream()
        ]
        review_decisions = [
            ReviewDecision.model_validate(_clean(d)) for d in self._col("reviews").stream()
        ]
        audits = [
            EvaluationAuditEvent.model_validate(_clean(d)) for d in self._col("audits").stream()
        ]
        idempotency = [
            EvaluationIdempotencyRecord.model_validate(_clean(d))
            for d in self._col("idempotency").stream()
        ]
        outbox_jobs = [_clean(d) for d in self._col("outbox_jobs").stream()]

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
            outbox_jobs=tuple(outbox_jobs),
        )
        with self._lock:
            self._state = loaded
        return loaded

    def get_case(self, case_id: str) -> EvalCase | None:
        with self._lock:
            cached = next((c for c in self._state.cases if c.case_id == case_id), None)
        if cached is not None:
            return cached
        doc = self._col("cases").document(case_id).get()
        if getattr(doc, "exists", False) and doc.to_dict():
            case = EvalCase.model_validate(strip_revision_metadata(dict(doc.to_dict())))
            with self._lock:
                if not any(c.case_id == case_id for c in self._state.cases):
                    self._state = self._state.model_copy(
                        update={"cases": self._state.cases + (case,)}
                    )
            return case
        return None

    def get_revision(self, revision_id: str) -> CaseRevision | None:
        with self._lock:
            cached = next((r for r in self._state.revisions if r.revision_id == revision_id), None)
        if cached is not None:
            return cached
        doc = self._col("revisions").document(revision_id).get()
        if getattr(doc, "exists", False) and doc.to_dict():
            rev = CaseRevision.model_validate(strip_revision_metadata(dict(doc.to_dict())))
            with self._lock:
                if not any(r.revision_id == revision_id for r in self._state.revisions):
                    self._state = self._state.model_copy(
                        update={"revisions": self._state.revisions + (rev,)}
                    )
            return rev
        return None

    def get_run(self, run_id: str) -> EvaluationRun | None:
        # Mutable entity: query Firestore so multi-instance updates are visible immediately.
        doc = self._col("runs").document(run_id).get()
        if getattr(doc, "exists", False) and doc.to_dict():
            run = EvaluationRun.model_validate(strip_revision_metadata(dict(doc.to_dict())))
            with self._lock:
                runs = [r for r in self._state.runs if r.run_id != run_id] + [run]
                self._state = self._state.model_copy(update={"runs": tuple(runs)})
            return run
        with self._lock:
            return next((r for r in self._state.runs if r.run_id == run_id), None)

    def get_case_execution(self, execution_id: str) -> CaseExecution | None:
        doc = self._col("executions").document(execution_id).get()
        if getattr(doc, "exists", False) and doc.to_dict():
            execution = CaseExecution.model_validate(
                strip_revision_metadata(dict(doc.to_dict()))
            )
            with self._lock:
                retained = [
                    item
                    for item in self._state.case_executions
                    if item.execution_id != execution_id
                ]
                self._state = self._state.model_copy(
                    update={"case_executions": tuple(retained + [execution])}
                )
            return execution
        with self._lock:
            return next(
                (e for e in self._state.case_executions if e.execution_id == execution_id),
                None,
            )

    def get_set(self, set_id: str) -> EvalSet | None:
        with self._lock:
            cached = next((s for s in self._state.sets if s.set_id == set_id), None)
        if cached is not None:
            return cached
        doc = self._col("sets").document(set_id).get()
        if getattr(doc, "exists", False) and doc.to_dict():
            eval_set = EvalSet.model_validate(strip_revision_metadata(dict(doc.to_dict())))
            with self._lock:
                if not any(s.set_id == set_id for s in self._state.sets):
                    self._state = self._state.model_copy(
                        update={"sets": self._state.sets + (eval_set,)}
                    )
            return eval_set
        return None

    def get_set_version(self, set_version_id: str) -> EvalSetVersion | None:
        with self._lock:
            cached = next(
                (v for v in self._state.set_versions if v.set_version_id == set_version_id),
                None,
            )
        if cached is not None:
            return cached
        doc = self._col("set_versions").document(set_version_id).get()
        if getattr(doc, "exists", False) and doc.to_dict():
            version = EvalSetVersion.model_validate(
                strip_revision_metadata(dict(doc.to_dict()))
            )
            with self._lock:
                if not any(
                    v.set_version_id == set_version_id for v in self._state.set_versions
                ):
                    self._state = self._state.model_copy(
                        update={"set_versions": self._state.set_versions + (version,)}
                    )
            return version
        return None

    def get_candidate_job(self, job_id: str) -> CandidateGenerationJob | None:
        doc = self._col("candidate_jobs").document(job_id).get()
        if getattr(doc, "exists", False) and doc.to_dict():
            job = CandidateGenerationJob.model_validate(
                strip_revision_metadata(dict(doc.to_dict()))
            )
            with self._lock:
                jobs = [j for j in self._state.candidate_jobs if j.job_id != job_id] + [job]
                self._state = self._state.model_copy(update={"candidate_jobs": tuple(jobs)})
            return job
        with self._lock:
            return next((j for j in self._state.candidate_jobs if j.job_id == job_id), None)

    def commit_mutation(
        self,
        new_state: EvaluationState,
        audit: EvaluationAuditEvent | None = None,
        idempotency_record: EvaluationIdempotencyRecord | None = None,
        expected_revision: int | None = None,
    ) -> None:
        meta_ref = self._col("meta").document("root")
        with self._lock:
            prev_state = self._state
        diff = compute_evaluation_state_diff(prev_state, new_state)

        def op(transaction: Any) -> int:
            curr_rev = read_meta_revision(meta_ref, transaction)
            if expected_revision is not None and curr_rev != expected_revision:
                raise EvaluationVersionConflictError(
                    f"Revision conflict: expected {expected_revision}, got {curr_rev}"
                )
            next_rev = curr_rev + 1
            transaction.set(meta_ref, {"revision": next_rev})
            apply_evaluation_state_diff(
                transaction,
                col=self._col,
                diff=diff,
                next_rev=next_rev,
                audit=audit,
                idempotency_record=idempotency_record,
            )
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

    def delete_outbox_jobs(self, outbox_ids: set[str] | list[str]) -> None:
        target_ids = {str(i) for i in outbox_ids}
        if not target_ids:
            return

        meta_ref = self._col("meta").document("root")

        def op(transaction: Any) -> int:
            next_rev = read_meta_revision(meta_ref, transaction) + 1
            transaction.set(meta_ref, {"revision": next_rev})
            for oid in target_ids:
                ref = self._col("outbox_jobs").document(oid)
                # Propagate Firestore failures; do not swallow like best-effort CAS deletes.
                if hasattr(transaction, "delete"):
                    transaction.delete(ref)
                elif hasattr(ref, "delete"):
                    ref.delete()
                elif hasattr(ref, "coll") and hasattr(ref.coll, "store"):
                    ref.coll.store.pop((ref.coll.name, ref.key), None)
            return next_rev

        next_rev = self._run_transaction(op)
        with self._lock:
            remaining = [
                j
                for j in getattr(self._state, "outbox_jobs", ())
                if outbox_key(j) not in target_ids
            ]
            self._state = self._state.model_copy(
                update={"outbox_jobs": tuple(remaining), "revision": next_rev}
            )

    def update_case(
        self,
        case: EvalCase,
        revision: CaseRevision | None = None,
        audit: EvaluationAuditEvent | None = None,
    ) -> None:
        meta_ref = self._col("meta").document("root")

        def op(transaction: Any) -> int:
            next_rev = read_meta_revision(meta_ref, transaction) + 1
            transaction.set(meta_ref, {"revision": next_rev})
            transaction.set(
                self._col("cases").document(case.case_id),
                model_document_payload(case, next_rev),
            )
            if revision:
                transaction.set(
                    self._col("revisions").document(revision.revision_id),
                    model_document_payload(revision, next_rev),
                )
            if audit:
                transaction.set(
                    self._col("audits").document(audit.audit_id),
                    model_document_payload(audit, next_rev),
                )
            return next_rev

        next_rev = self._run_transaction(op)
        with self._lock:
            cases = [c for c in self._state.cases if c.case_id != case.case_id] + [case]
            revisions = list(self._state.revisions)
            if revision and not any(r.revision_id == revision.revision_id for r in revisions):
                revisions.append(revision)
            audits = list(self._state.audits)
            if audit:
                audits.append(audit)
            self._state = self._state.model_copy(
                update={
                    "revision": next_rev,
                    "cases": tuple(cases),
                    "revisions": tuple(revisions),
                    "audits": tuple(audits),
                }
            )

    def update_run(
        self,
        run: EvaluationRun,
        executions: list[CaseExecution] | None = None,
        audit: EvaluationAuditEvent | None = None,
    ) -> None:
        meta_ref = self._col("meta").document("root")

        def op(transaction: Any) -> int:
            next_rev = read_meta_revision(meta_ref, transaction) + 1
            transaction.set(meta_ref, {"revision": next_rev})
            transaction.set(
                self._col("runs").document(run.run_id),
                model_document_payload(run, next_rev),
            )
            if executions:
                for execution in executions:
                    transaction.set(
                        self._col("executions").document(execution.execution_id),
                        model_document_payload(execution, next_rev),
                    )
            if audit:
                transaction.set(
                    self._col("audits").document(audit.audit_id),
                    model_document_payload(audit, next_rev),
                )
            return next_rev

        next_rev = self._run_transaction(op)
        with self._lock:
            runs = [r for r in self._state.runs if r.run_id != run.run_id] + [run]
            case_execs = list(self._state.case_executions)
            if executions:
                exec_ids = {e.execution_id for e in executions}
                case_execs = [e for e in case_execs if e.execution_id not in exec_ids] + executions
            audits = list(self._state.audits)
            if audit:
                audits.append(audit)
            self._state = self._state.model_copy(
                update={
                    "revision": next_rev,
                    "runs": tuple(runs),
                    "case_executions": tuple(case_execs),
                    "audits": tuple(audits),
                }
            )
