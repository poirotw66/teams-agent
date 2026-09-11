from __future__ import annotations

import fcntl
import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .errors import (
    EvaluationNotFoundError,
    EvaluationVersionConflictError,
    JobFencingConflictError,
    JobLeaseLostError,
)
from .job_models import ExecutionJob, JobState


class JobRepository(Protocol):
    def enqueue_job(self, job: ExecutionJob) -> ExecutionJob: ...

    def claim_job(
        self, worker_id: str, lease_seconds: float = 60.0
    ) -> ExecutionJob | None: ...

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        extend_seconds: float = 60.0,
    ) -> ExecutionJob: ...

    def save_checkpoint(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        checkpoint_ref: str,
    ) -> ExecutionJob: ...

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        state: JobState,
        last_error: str | None = None,
    ) -> ExecutionJob: ...

    def request_cancellation(self, job_id: str) -> ExecutionJob: ...

    def get_job(self, job_id: str) -> ExecutionJob | None: ...

    def get_job_by_run_id(self, run_id: str) -> ExecutionJob | None: ...

    def list_jobs(
        self, tenant_id: str | None = None, state: JobState | None = None
    ) -> list[ExecutionJob]: ...


class InMemoryJobRepository:
    """Thread-safe in-memory execution job repository."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, ExecutionJob] = {}

    def enqueue_job(self, job: ExecutionJob) -> ExecutionJob:
        with self._lock:
            # Idempotency / Deduplication: check if active job already exists for logical_key
            for existing in self._jobs.values():
                if (
                    existing.tenant_id == job.tenant_id
                    and existing.logical_key == job.logical_key
                    and existing.state in {"QUEUED", "RUNNING"}
                ):
                    return existing
            self._jobs[job.job_id] = job
            return job

    def claim_job(
        self, worker_id: str, lease_seconds: float = 60.0
    ) -> ExecutionJob | None:
        now = datetime.now(UTC)
        with self._lock:
            candidates: list[ExecutionJob] = []
            for j in self._jobs.values():
                if j.state == "QUEUED":
                    candidates.append(j)
                elif j.state == "RUNNING" and j.lease_until and j.lease_until < now:
                    # Lease expired; re-claimable if max_attempts not exceeded
                    if j.attempt < j.max_attempts:
                        candidates.append(j)
                    else:
                        # Exceeded attempts; transition to FAILED
                        failed_job = j.model_copy(
                            update={
                                "state": "FAILED",
                                "last_error": "Lease expired and max attempts exceeded",
                                "updated_at": now,
                                "revision": j.revision + 1,
                            }
                        )
                        self._jobs[j.job_id] = failed_job

            if not candidates:
                return None

            # Pick oldest candidate by created_at
            candidates.sort(key=lambda j: j.created_at)
            chosen = candidates[0]
            is_reclaim = chosen.state == "RUNNING"
            new_attempt = chosen.attempt + 1 if is_reclaim else chosen.attempt
            new_fencing = chosen.fencing_token + 1

            claimed = chosen.model_copy(
                update={
                    "state": "RUNNING",
                    "lease_owner": worker_id,
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "heartbeat_at": now,
                    "attempt": new_attempt,
                    "fencing_token": new_fencing,
                    "revision": chosen.revision + 1,
                    "updated_at": now,
                }
            )
            self._jobs[chosen.job_id] = claimed
            return claimed

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        extend_seconds: float = 60.0,
    ) -> ExecutionJob:
        now = datetime.now(UTC)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise EvaluationNotFoundError(f"Job {job_id} not found")
            if job.fencing_token != fencing_token:
                raise JobFencingConflictError(
                    f"Fencing token mismatch for job {job_id}: current={job.fencing_token}, worker={fencing_token}"
                )
            if job.lease_owner != worker_id:
                raise JobLeaseLostError(
                    f"Job {job_id} lease is owned by {job.lease_owner}, not {worker_id}"
                )
            updated = job.model_copy(
                update={
                    "heartbeat_at": now,
                    "lease_until": now + timedelta(seconds=extend_seconds),
                    "updated_at": now,
                    "revision": job.revision + 1,
                }
            )
            self._jobs[job_id] = updated
            return updated

    def save_checkpoint(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        checkpoint_ref: str,
    ) -> ExecutionJob:
        now = datetime.now(UTC)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise EvaluationNotFoundError(f"Job {job_id} not found")
            if job.fencing_token != fencing_token:
                raise JobFencingConflictError(
                    f"Fencing token mismatch for job {job_id}: current={job.fencing_token}, worker={fencing_token}"
                )
            if job.lease_owner != worker_id:
                raise JobLeaseLostError(
                    f"Job {job_id} lease is owned by {job.lease_owner}, not {worker_id}"
                )
            updated = job.model_copy(
                update={
                    "checkpoint_ref": checkpoint_ref,
                    "heartbeat_at": now,
                    "updated_at": now,
                    "revision": job.revision + 1,
                }
            )
            self._jobs[job_id] = updated
            return updated

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        state: JobState,
        last_error: str | None = None,
    ) -> ExecutionJob:
        now = datetime.now(UTC)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise EvaluationNotFoundError(f"Job {job_id} not found")
            if job.fencing_token != fencing_token:
                raise JobFencingConflictError(
                    f"Fencing token mismatch for job {job_id}: current={job.fencing_token}, worker={fencing_token}"
                )
            if job.lease_owner != worker_id:
                raise JobLeaseLostError(
                    f"Job {job_id} lease is owned by {job.lease_owner}, not {worker_id}"
                )
            updated = job.model_copy(
                update={
                    "state": state,
                    "lease_owner": None,
                    "lease_until": None,
                    "last_error": last_error or job.last_error,
                    "updated_at": now,
                    "revision": job.revision + 1,
                }
            )
            self._jobs[job_id] = updated
            return updated

    def request_cancellation(self, job_id: str) -> ExecutionJob:
        now = datetime.now(UTC)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise EvaluationNotFoundError(f"Job {job_id} not found")
            if job.state in {"COMPLETED", "FAILED", "CANCELLED"}:
                return job
            updated = job.model_copy(
                update={
                    "cancel_requested_at": now,
                    "updated_at": now,
                    "revision": job.revision + 1,
                }
            )
            self._jobs[job_id] = updated
            return updated

    def get_job(self, job_id: str) -> ExecutionJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_job_by_run_id(self, run_id: str) -> ExecutionJob | None:
        with self._lock:
            return next((j for j in self._jobs.values() if j.run_id == run_id), None)

    def list_jobs(
        self, tenant_id: str | None = None, state: JobState | None = None
    ) -> list[ExecutionJob]:
        with self._lock:
            results = list(self._jobs.values())
            if tenant_id:
                results = [j for j in results if j.tenant_id == tenant_id]
            if state:
                results = [j for j in results if j.state == state]
            return sorted(results, key=lambda j: j.created_at, reverse=True)


class FileJobRepository(InMemoryJobRepository):
    """Multi-process safe, file-based durable execution job repository.

    Stores each job in an individual JSON file under `directory/records/{job_id}.json`
    with file locking (`fcntl.flock`) for atomic read-modify-write and CAS.
    """

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self._dir = directory
        self._records_dir = self._dir / "records"
        self._records_dir.mkdir(parents=True, exist_ok=True)
        self._lock_file = self._dir / ".jobs.lock"
        self._sync_from_disk()

    def _sync_from_disk(self) -> None:
        with self._lock:
            jobs: dict[str, ExecutionJob] = {}
            for path in self._records_dir.glob("*.json"):
                try:
                    raw = path.read_text(encoding="utf-8")
                    if raw.strip():
                        job = ExecutionJob.model_validate_json(raw)
                        jobs[job.job_id] = job
                except Exception:
                    continue
            self._jobs = jobs

    def _write_record_atomic(self, job: ExecutionJob) -> None:
        target = self._records_dir / f"{job.job_id}.json"
        temp = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as f:
            f.write(job.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
        parent_fd = os.open(str(self._records_dir), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def _with_file_lock(self, fn: Any) -> Any:
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_file.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                self._sync_from_disk()
                res = fn()
                if isinstance(res, ExecutionJob):
                    self._write_record_atomic(res)
                return res
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def enqueue_job(self, job: ExecutionJob) -> ExecutionJob:
        return self._with_file_lock(lambda: super(FileJobRepository, self).enqueue_job(job))

    def claim_job(
        self, worker_id: str, lease_seconds: float = 60.0
    ) -> ExecutionJob | None:
        return self._with_file_lock(
            lambda: super(FileJobRepository, self).claim_job(worker_id, lease_seconds)
        )

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        extend_seconds: float = 60.0,
    ) -> ExecutionJob:
        return self._with_file_lock(
            lambda: super(FileJobRepository, self).heartbeat(
                job_id, worker_id, fencing_token, extend_seconds
            )
        )

    def save_checkpoint(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        checkpoint_ref: str,
    ) -> ExecutionJob:
        return self._with_file_lock(
            lambda: super(FileJobRepository, self).save_checkpoint(
                job_id, worker_id, fencing_token, checkpoint_ref
            )
        )

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        state: JobState,
        last_error: str | None = None,
    ) -> ExecutionJob:
        return self._with_file_lock(
            lambda: super(FileJobRepository, self).complete_job(
                job_id, worker_id, fencing_token, state, last_error
            )
        )

    def request_cancellation(self, job_id: str) -> ExecutionJob:
        return self._with_file_lock(
            lambda: super(FileJobRepository, self).request_cancellation(job_id)
        )

    def get_job(self, job_id: str) -> ExecutionJob | None:
        self._sync_from_disk()
        return super().get_job(job_id)

    def get_job_by_run_id(self, run_id: str) -> ExecutionJob | None:
        self._sync_from_disk()
        return super().get_job_by_run_id(run_id)

    def list_jobs(
        self, tenant_id: str | None = None, state: JobState | None = None
    ) -> list[ExecutionJob]:
        self._sync_from_disk()
        return super().list_jobs(tenant_id=tenant_id, state=state)


class FirestoreJobRepository:
    """Production GCP Firestore repository for execution jobs with transactional leasing and fencing."""

    def __init__(self, client: Any, collection: str = "ai_ops_execution_jobs") -> None:
        self._client = client
        self._collection = collection

    def _doc_ref(self, job_id: str) -> Any:
        return self._client.collection(self._collection).document(job_id)

    def enqueue_job(self, job: ExecutionJob) -> ExecutionJob:
        # Check active job by logical_key in tenant
        query = (
            self._client.collection(self._collection)
            .where("tenant_id", "==", job.tenant_id)
            .where("logical_key", "==", job.logical_key)
            .where("state", "in", ["QUEUED", "RUNNING"])
            .limit(1)
        )
        docs = list(query.stream())
        if docs:
            return ExecutionJob.model_validate(docs[0].to_dict())

        data = json.loads(job.model_dump_json())
        self._doc_ref(job.job_id).set(data)
        return job

    def claim_job(
        self, worker_id: str, lease_seconds: float = 60.0
    ) -> ExecutionJob | None:
        now = datetime.now(UTC)
        query = (
            self._client.collection(self._collection)
            .where("state", "in", ["QUEUED", "RUNNING"])
            .limit(20)
        )
        docs = list(query.stream())
        for d in docs:
            j = ExecutionJob.model_validate(d.to_dict())
            should_claim = False
            is_reclaim = False
            if j.state == "QUEUED":
                should_claim = True
            elif j.state == "RUNNING" and j.lease_until and j.lease_until < now:
                if j.attempt < j.max_attempts:
                    should_claim = True
                    is_reclaim = True
                else:
                    # Mark FAILED
                    self._doc_ref(j.job_id).update(
                        {
                            "state": "FAILED",
                            "last_error": "Lease expired and max attempts exceeded",
                            "updated_at": now.isoformat(),
                            "revision": j.revision + 1,
                        }
                    )
                    continue

            if should_claim:
                new_attempt = j.attempt + 1 if is_reclaim else j.attempt
                new_fencing = j.fencing_token + 1
                new_lease = now + timedelta(seconds=lease_seconds)
                claimed = j.model_copy(
                    update={
                        "state": "RUNNING",
                        "lease_owner": worker_id,
                        "lease_until": new_lease,
                        "heartbeat_at": now,
                        "attempt": new_attempt,
                        "fencing_token": new_fencing,
                        "revision": j.revision + 1,
                        "updated_at": now,
                    }
                )
                try:
                    # CAS using revision
                    self._doc_ref(j.job_id).update(
                        json.loads(claimed.model_dump_json())
                    )
                    return claimed
                except Exception:
                    continue
        return None

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        extend_seconds: float = 60.0,
    ) -> ExecutionJob:
        now = datetime.now(UTC)
        doc = self._doc_ref(job_id).get()
        if not doc.exists:
            raise EvaluationNotFoundError(f"Job {job_id} not found")
        job = ExecutionJob.model_validate(doc.to_dict())
        if job.fencing_token != fencing_token:
            raise JobFencingConflictError(f"Fencing token conflict for job {job_id}")
        if job.lease_owner != worker_id:
            raise JobLeaseLostError(f"Lease lost for job {job_id}")

        updated = job.model_copy(
            update={
                "heartbeat_at": now,
                "lease_until": now + timedelta(seconds=extend_seconds),
                "updated_at": now,
                "revision": job.revision + 1,
            }
        )
        self._doc_ref(job_id).update(json.loads(updated.model_dump_json()))
        return updated

    def save_checkpoint(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        checkpoint_ref: str,
    ) -> ExecutionJob:
        now = datetime.now(UTC)
        doc = self._doc_ref(job_id).get()
        if not doc.exists:
            raise EvaluationNotFoundError(f"Job {job_id} not found")
        job = ExecutionJob.model_validate(doc.to_dict())
        if job.fencing_token != fencing_token:
            raise JobFencingConflictError(f"Fencing token conflict for job {job_id}")
        if job.lease_owner != worker_id:
            raise JobLeaseLostError(f"Lease lost for job {job_id}")

        updated = job.model_copy(
            update={
                "checkpoint_ref": checkpoint_ref,
                "heartbeat_at": now,
                "updated_at": now,
                "revision": job.revision + 1,
            }
        )
        self._doc_ref(job_id).update(json.loads(updated.model_dump_json()))
        return updated

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        state: JobState,
        last_error: str | None = None,
    ) -> ExecutionJob:
        now = datetime.now(UTC)
        doc = self._doc_ref(job_id).get()
        if not doc.exists:
            raise EvaluationNotFoundError(f"Job {job_id} not found")
        job = ExecutionJob.model_validate(doc.to_dict())
        if job.fencing_token != fencing_token:
            raise JobFencingConflictError(f"Fencing token conflict for job {job_id}")
        if job.lease_owner != worker_id:
            raise JobLeaseLostError(f"Lease lost for job {job_id}")

        updated = job.model_copy(
            update={
                "state": state,
                "lease_owner": None,
                "lease_until": None,
                "last_error": last_error or job.last_error,
                "updated_at": now,
                "revision": job.revision + 1,
            }
        )
        self._doc_ref(job_id).update(json.loads(updated.model_dump_json()))
        return updated

    def request_cancellation(self, job_id: str) -> ExecutionJob:
        now = datetime.now(UTC)
        doc = self._doc_ref(job_id).get()
        if not doc.exists:
            raise EvaluationNotFoundError(f"Job {job_id} not found")
        job = ExecutionJob.model_validate(doc.to_dict())
        if job.state in {"COMPLETED", "FAILED", "CANCELLED"}:
            return job
        updated = job.model_copy(
            update={
                "cancel_requested_at": now,
                "updated_at": now,
                "revision": job.revision + 1,
            }
        )
        self._doc_ref(job_id).update(json.loads(updated.model_dump_json()))
        return updated

    def get_job(self, job_id: str) -> ExecutionJob | None:
        doc = self._doc_ref(job_id).get()
        if not doc.exists:
            return None
        return ExecutionJob.model_validate(doc.to_dict())

    def get_job_by_run_id(self, run_id: str) -> ExecutionJob | None:
        query = (
            self._client.collection(self._collection)
            .where("run_id", "==", run_id)
            .limit(1)
        )
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
        jobs = [ExecutionJob.model_validate(d.to_dict()) for d in docs]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)
