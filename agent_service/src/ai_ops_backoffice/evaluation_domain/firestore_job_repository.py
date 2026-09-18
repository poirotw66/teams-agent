"""Firestore-backed execution job repository with transactional leasing."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from .errors import EvaluationNotFoundError
from .job_lease_ops import (
    ACTIVE_OR_TERMINAL_STATES,
    apply_cancel_request,
    apply_checkpoint,
    apply_completion,
    apply_heartbeat,
    assert_lease_ownership,
    build_claimed_job,
    job_document_payload,
    utc_now,
)
from .job_models import ExecutionJob, JobState

logger = logging.getLogger(__name__)


class FirestoreJobRepository:
    """Production GCP Firestore repository for execution jobs with transactional leasing and fencing."""

    def __init__(
        self,
        client: Any,
        collection: str = "ai_ops_execution_jobs",
        transaction_runner: Any = None,
    ) -> None:
        self._client = client
        self._collection = collection
        self._transaction_runner = transaction_runner

    def _doc_ref(self, job_id: str) -> Any:
        return self._client.collection(self._collection).document(job_id)

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
                if hasattr(ref, "set"):
                    ref.set(data, merge=merge)

            def update(self, ref: Any, data: Any) -> None:
                if hasattr(ref, "update"):
                    ref.update(data)
                elif hasattr(ref, "set"):
                    ref.set(data)

        return operation(_ImmediateTx())

    def enqueue_job(self, job: ExecutionJob) -> ExecutionJob:
        """Enqueue with transactional logical-key dedup via a deterministic dedup document."""
        digest = hashlib.sha256(f"{job.tenant_id}:{job.logical_key}".encode()).hexdigest()[:32]
        dedup_id = f"lk_{job.tenant_id}_{digest}"
        dedup_ref = self._client.collection(self._collection).document(dedup_id)
        job_ref = self._doc_ref(job.job_id)

        def enqueue_tx(transaction: Any) -> ExecutionJob:
            job_snap = job_ref.get(transaction=transaction)
            if getattr(job_snap, "exists", False):
                return ExecutionJob.model_validate(job_snap.to_dict())

            dedup_snap = dedup_ref.get(transaction=transaction)
            if getattr(dedup_snap, "exists", False):
                existing_id = (dedup_snap.to_dict() or {}).get("job_id")
                if existing_id:
                    existing_ref = self._doc_ref(existing_id)
                    existing_snap = existing_ref.get(transaction=transaction)
                    if getattr(existing_snap, "exists", False):
                        existing = ExecutionJob.model_validate(existing_snap.to_dict())
                        if existing.state in ACTIVE_OR_TERMINAL_STATES:
                            return existing
            data = job_document_payload(job)
            transaction.set(job_ref, data)
            transaction.set(
                dedup_ref,
                {
                    "job_id": job.job_id,
                    "tenant_id": job.tenant_id,
                    "logical_key": job.logical_key,
                    "state": job.state,
                },
            )
            return job

        return self._run_transaction(enqueue_tx)

    def claim_job(self, worker_id: str, lease_seconds: float = 60.0) -> ExecutionJob | None:
        query = (
            self._client.collection(self._collection)
            .where("state", "in", ["QUEUED", "RUNNING"])
            .limit(20)
        )
        docs = list(query.stream())
        for doc in docs:
            doc_ref = self._doc_ref(doc.id)

            def claim_tx(transaction: Any, doc_ref: Any = doc_ref) -> ExecutionJob | None:
                curr_now = utc_now()
                snap = doc_ref.get(transaction=transaction)
                if not getattr(snap, "exists", False):
                    return None
                job = ExecutionJob.model_validate(snap.to_dict())
                should_claim = False
                is_reclaim = False
                if job.state == "QUEUED":
                    should_claim = True
                elif job.state == "RUNNING" and job.lease_until and job.lease_until < curr_now:
                    if job.attempt < job.max_attempts:
                        should_claim = True
                        is_reclaim = True
                    else:
                        failed_payload = {
                            **snap.to_dict(),
                            "state": "FAILED",
                            "last_error": "Lease expired and max attempts exceeded",
                            "updated_at": curr_now.isoformat(),
                            "revision": job.revision + 1,
                        }
                        transaction.set(doc_ref, failed_payload)
                        return None

                if not should_claim:
                    return None

                claimed = build_claimed_job(
                    job,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    now=curr_now,
                    is_reclaim=is_reclaim,
                )
                transaction.set(doc_ref, job_document_payload(claimed))
                return claimed

            try:
                claimed_job = self._run_transaction(claim_tx)
                if claimed_job is not None:
                    return claimed_job
            except Exception:
                logger.warning("Skipping claim failure for job doc %s", doc.id, exc_info=True)
                continue
        return None

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        extend_seconds: float = 60.0,
    ) -> ExecutionJob:
        doc_ref = self._doc_ref(job_id)

        def hb_tx(transaction: Any) -> ExecutionJob:
            now = utc_now()
            snap = doc_ref.get(transaction=transaction)
            if not getattr(snap, "exists", False):
                raise EvaluationNotFoundError(f"Job {job_id} not found")
            job = ExecutionJob.model_validate(snap.to_dict())
            assert_lease_ownership(
                job,
                worker_id=worker_id,
                fencing_token=fencing_token,
                strict_messages=False,
            )
            updated = apply_heartbeat(job, extend_seconds=extend_seconds, now=now)
            transaction.set(doc_ref, job_document_payload(updated))
            return updated

        return self._run_transaction(hb_tx)

    def save_checkpoint(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        checkpoint_ref: str,
    ) -> ExecutionJob:
        doc_ref = self._doc_ref(job_id)

        def cp_tx(transaction: Any) -> ExecutionJob:
            now = utc_now()
            snap = doc_ref.get(transaction=transaction)
            if not getattr(snap, "exists", False):
                raise EvaluationNotFoundError(f"Job {job_id} not found")
            job = ExecutionJob.model_validate(snap.to_dict())
            assert_lease_ownership(
                job,
                worker_id=worker_id,
                fencing_token=fencing_token,
                strict_messages=False,
            )
            updated = apply_checkpoint(job, checkpoint_ref=checkpoint_ref, now=now)
            transaction.set(doc_ref, job_document_payload(updated))
            return updated

        return self._run_transaction(cp_tx)

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        state: JobState,
        last_error: str | None = None,
    ) -> ExecutionJob:
        doc_ref = self._doc_ref(job_id)

        def comp_tx(transaction: Any) -> ExecutionJob:
            now = utc_now()
            snap = doc_ref.get(transaction=transaction)
            if not getattr(snap, "exists", False):
                raise EvaluationNotFoundError(f"Job {job_id} not found")
            job = ExecutionJob.model_validate(snap.to_dict())
            assert_lease_ownership(
                job,
                worker_id=worker_id,
                fencing_token=fencing_token,
                strict_messages=False,
            )
            updated = apply_completion(job, state=state, last_error=last_error, now=now)
            transaction.set(doc_ref, job_document_payload(updated))
            return updated

        return self._run_transaction(comp_tx)

    def request_cancellation(self, job_id: str) -> ExecutionJob:
        doc_ref = self._doc_ref(job_id)

        def cancel_tx(transaction: Any) -> ExecutionJob:
            now = utc_now()
            snap = doc_ref.get(transaction=transaction)
            if not getattr(snap, "exists", False):
                raise EvaluationNotFoundError(f"Job {job_id} not found")
            job = ExecutionJob.model_validate(snap.to_dict())
            updated = apply_cancel_request(job, now=now)
            if updated is job:
                return job
            transaction.set(doc_ref, job_document_payload(updated))
            return updated

        return self._run_transaction(cancel_tx)

    def get_job(self, job_id: str) -> ExecutionJob | None:
        doc = self._doc_ref(job_id).get()
        if not doc.exists:
            return None
        return ExecutionJob.model_validate(doc.to_dict())

    def get_job_by_run_id(self, run_id: str) -> ExecutionJob | None:
        query = self._client.collection(self._collection).where("run_id", "==", run_id).limit(1)
        docs = list(query.stream())
        if not docs:
            return None
        return ExecutionJob.model_validate(docs[0].to_dict())

    def list_jobs(
        self, tenant_id: str | None = None, state: JobState | None = None
    ) -> list[ExecutionJob]:
        query = self._client.collection(self._collection)
        if tenant_id:
            query = query.where("tenant_id", "==", tenant_id)
        if state:
            query = query.where("state", "==", state)
        docs = list(query.stream())
        jobs = [ExecutionJob.model_validate(doc.to_dict()) for doc in docs]
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)
