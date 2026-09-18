"""Firestore mutation helpers for evaluation state persistence."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

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

CollectionFn = Callable[[str], Any]


@dataclass(frozen=True)
class EvaluationStateDiff:
    """Changed and deleted entity ids between two evaluation states."""

    changed_cases: tuple[EvalCase, ...]
    deleted_case_ids: frozenset[str]
    changed_revisions: tuple[CaseRevision, ...]
    deleted_revision_ids: frozenset[str]
    changed_sets: tuple[EvalSet, ...]
    deleted_set_ids: frozenset[str]
    changed_set_versions: tuple[EvalSetVersion, ...]
    deleted_set_version_ids: frozenset[str]
    changed_candidate_jobs: tuple[CandidateGenerationJob, ...]
    deleted_candidate_job_ids: frozenset[str]
    changed_runs: tuple[EvaluationRun, ...]
    deleted_run_ids: frozenset[str]
    changed_executions: tuple[CaseExecution, ...]
    deleted_execution_ids: frozenset[str]
    changed_review_decisions: tuple[ReviewDecision, ...]
    deleted_review_decision_ids: frozenset[str]
    changed_outbox: tuple[dict[str, Any], ...]
    deleted_outbox_ids: frozenset[str]


def strip_revision_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Drop internal CAS revision metadata from a Firestore document payload."""
    cleaned = dict(data)
    cleaned.pop("_revision", None)
    return cleaned


def model_document_payload(model: BaseModel, revision: int) -> dict[str, Any]:
    """Serialize a pydantic model for Firestore and stamp the CAS revision."""
    data = json.loads(model.model_dump_json())
    data["_revision"] = revision
    return data


def outbox_key(job: dict[str, Any]) -> str:
    return str(job.get("outbox_id", job.get("job_id")))


def compute_evaluation_state_diff(
    prev_state: EvaluationState, new_state: EvaluationState
) -> EvaluationStateDiff:
    """Compute per-collection diffs so mutations write only changed documents."""
    prev_cases = {c.case_id: c for c in prev_state.cases}
    prev_revs = {r.revision_id: r for r in prev_state.revisions}
    prev_sets = {s.set_id: s for s in prev_state.sets}
    prev_svs = {sv.set_version_id: sv for sv in prev_state.set_versions}
    prev_cjobs = {j.job_id: j for j in prev_state.candidate_jobs}
    prev_runs = {r.run_id: r for r in prev_state.runs}
    prev_execs = {e.execution_id: e for e in prev_state.case_executions}
    prev_rev_decs = {d.decision_id: d for d in prev_state.review_decisions}
    prev_outbox = {outbox_key(j): j for j in getattr(prev_state, "outbox_jobs", ())}
    new_outbox = {outbox_key(j): j for j in getattr(new_state, "outbox_jobs", ())}

    return EvaluationStateDiff(
        changed_cases=tuple(c for c in new_state.cases if prev_cases.get(c.case_id) != c),
        deleted_case_ids=frozenset(prev_cases.keys()) - {c.case_id for c in new_state.cases},
        changed_revisions=tuple(
            r for r in new_state.revisions if prev_revs.get(r.revision_id) != r
        ),
        deleted_revision_ids=frozenset(prev_revs.keys())
        - {r.revision_id for r in new_state.revisions},
        changed_sets=tuple(s for s in new_state.sets if prev_sets.get(s.set_id) != s),
        deleted_set_ids=frozenset(prev_sets.keys()) - {s.set_id for s in new_state.sets},
        changed_set_versions=tuple(
            sv for sv in new_state.set_versions if prev_svs.get(sv.set_version_id) != sv
        ),
        deleted_set_version_ids=frozenset(prev_svs.keys())
        - {sv.set_version_id for sv in new_state.set_versions},
        changed_candidate_jobs=tuple(
            j for j in new_state.candidate_jobs if prev_cjobs.get(j.job_id) != j
        ),
        deleted_candidate_job_ids=frozenset(prev_cjobs.keys())
        - {j.job_id for j in new_state.candidate_jobs},
        changed_runs=tuple(r for r in new_state.runs if prev_runs.get(r.run_id) != r),
        deleted_run_ids=frozenset(prev_runs.keys()) - {r.run_id for r in new_state.runs},
        changed_executions=tuple(
            e for e in new_state.case_executions if prev_execs.get(e.execution_id) != e
        ),
        deleted_execution_ids=frozenset(prev_execs.keys())
        - {e.execution_id for e in new_state.case_executions},
        changed_review_decisions=tuple(
            d for d in new_state.review_decisions if prev_rev_decs.get(d.decision_id) != d
        ),
        deleted_review_decision_ids=frozenset(prev_rev_decs.keys())
        - {d.decision_id for d in new_state.review_decisions},
        changed_outbox=tuple(j for key, j in new_outbox.items() if prev_outbox.get(key) != j),
        deleted_outbox_ids=frozenset(prev_outbox.keys()) - frozenset(new_outbox.keys()),
    )


def safe_delete_document(transaction: Any, collection: Any, doc_id: str) -> None:
    """Best-effort delete that supports real Firestore txs and in-memory test doubles."""
    ref = collection.document(doc_id)
    if hasattr(transaction, "delete"):
        try:
            transaction.delete(ref)
            return
        except Exception:
            pass
    if hasattr(ref, "delete"):
        try:
            ref.delete()
            return
        except Exception:
            pass
    if hasattr(ref, "coll") and hasattr(ref.coll, "store"):
        ref.coll.store.pop((ref.coll.name, ref.key), None)


def write_model_collection(
    transaction: Any,
    collection: Any,
    *,
    models: tuple[BaseModel, ...] | list[BaseModel],
    id_attr: str,
    deleted_ids: frozenset[str],
    next_rev: int,
) -> None:
    """Upsert changed models and delete removed ids within one collection."""
    for model in models:
        ref = collection.document(getattr(model, id_attr))
        transaction.set(ref, model_document_payload(model, next_rev))
    for doc_id in deleted_ids:
        safe_delete_document(transaction, collection, doc_id)


def _entity_write_specs(
    diff: EvaluationStateDiff,
) -> tuple[tuple[str, tuple[BaseModel, ...], str, frozenset[str]], ...]:
    """Collection write specs shared by mutation transactions."""
    return (
        ("cases", diff.changed_cases, "case_id", diff.deleted_case_ids),
        ("revisions", diff.changed_revisions, "revision_id", diff.deleted_revision_ids),
        ("sets", diff.changed_sets, "set_id", diff.deleted_set_ids),
        (
            "set_versions",
            diff.changed_set_versions,
            "set_version_id",
            diff.deleted_set_version_ids,
        ),
        (
            "candidate_jobs",
            diff.changed_candidate_jobs,
            "job_id",
            diff.deleted_candidate_job_ids,
        ),
        ("runs", diff.changed_runs, "run_id", diff.deleted_run_ids),
        ("executions", diff.changed_executions, "execution_id", diff.deleted_execution_ids),
        (
            "reviews",
            diff.changed_review_decisions,
            "decision_id",
            diff.deleted_review_decision_ids,
        ),
    )


def apply_evaluation_state_diff(
    transaction: Any,
    *,
    col: CollectionFn,
    diff: EvaluationStateDiff,
    next_rev: int,
    audit: EvaluationAuditEvent | None = None,
    idempotency_record: EvaluationIdempotencyRecord | None = None,
) -> None:
    """Apply a computed state diff to Firestore collections inside a transaction."""
    for collection_name, models, id_attr, deleted_ids in _entity_write_specs(diff):
        write_model_collection(
            transaction,
            col(collection_name),
            models=models,
            id_attr=id_attr,
            deleted_ids=deleted_ids,
            next_rev=next_rev,
        )
    for outbox_job in diff.changed_outbox:
        oid = outbox_key(outbox_job)
        transaction.set(col("outbox_jobs").document(oid), {**outbox_job, "_revision": next_rev})
    for oid in diff.deleted_outbox_ids:
        safe_delete_document(transaction, col("outbox_jobs"), oid)
    if audit is not None:
        transaction.set(
            col("audits").document(audit.audit_id),
            model_document_payload(audit, next_rev),
        )
    if idempotency_record is not None:
        transaction.set(
            col("idempotency").document(idempotency_record.key),
            model_document_payload(idempotency_record, next_rev),
        )


def read_meta_revision(meta_ref: Any, transaction: Any | None = None) -> int:
    """Read the root meta revision, defaulting to 1 when the document is absent."""
    if transaction is None:
        meta_snap = meta_ref.get() if hasattr(meta_ref, "get") else None
    else:
        meta_snap = meta_ref.get(transaction=transaction) if hasattr(meta_ref, "get") else None
    if meta_snap and getattr(meta_snap, "exists", False):
        return int(meta_snap.to_dict().get("revision", 1))
    return 1


def run_client_transaction(client: Any, operation: Any, transaction_runner: Any = None) -> Any:
    """Execute ``operation`` under the client transaction API or an injected runner."""
    if transaction_runner is not None:
        tx = client.transaction() if hasattr(client, "transaction") else None
        return transaction_runner(operation, tx)
    if hasattr(client, "transaction"):
        try:
            from google.cloud.firestore_v1.transaction import transactional

            return transactional(operation)(client.transaction())
        except (ImportError, Exception):
            tx = client.transaction()
            result = operation(tx)
            if hasattr(tx, "commit"):
                tx.commit()
            return result

    class _ImmediateTx:
        def get(self, ref: Any) -> Any:
            return ref.get()

        def set(self, ref: Any, data: Any, merge: bool = False) -> None:
            if hasattr(ref, "set"):
                ref.set(data, merge=merge)

        def update(self, ref: Any, data: Any) -> None:
            if hasattr(ref, "update"):
                ref.update(data)
            elif hasattr(ref, "set"):
                ref.set(data)

        def delete(self, ref: Any) -> None:
            if hasattr(ref, "delete"):
                ref.delete()

    return operation(_ImmediateTx())
