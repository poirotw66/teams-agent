"""Execution job repository port and in-memory implementation.

File and Firestore adapters live in dedicated modules and are re-exported here
so existing ``from .job_repository import ...`` imports keep working.
"""

from __future__ import annotations

import threading
from typing import Protocol

from .job_lease_ops import (
    apply_cancel_request,
    apply_checkpoint,
    apply_completion,
    apply_heartbeat,
    assert_lease_ownership,
    build_claimed_job,
    build_max_attempts_failed_job,
    filter_jobs,
    find_logical_key_duplicate,
    require_job,
    utc_now,
)
from .job_models import ExecutionJob, JobState


class JobRepository(Protocol):
    def enqueue_job(self, job: ExecutionJob) -> ExecutionJob: ...

    def claim_job(self, worker_id: str, lease_seconds: float = 60.0) -> ExecutionJob | None: ...

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
            if job.job_id in self._jobs:
                return self._jobs[job.job_id]
            duplicate = find_logical_key_duplicate(list(self._jobs.values()), job)
            if duplicate is not None:
                return duplicate
            self._jobs[job.job_id] = job
            return job

    def claim_job(self, worker_id: str, lease_seconds: float = 60.0) -> ExecutionJob | None:
        now = utc_now()
        with self._lock:
            candidates: list[ExecutionJob] = []
            for job in self._jobs.values():
                if job.state == "QUEUED":
                    candidates.append(job)
                elif job.state == "RUNNING" and job.lease_until and job.lease_until < now:
                    if job.attempt < job.max_attempts:
                        candidates.append(job)
                    else:
                        self._jobs[job.job_id] = build_max_attempts_failed_job(job, now=now)

            if not candidates:
                return None

            candidates.sort(key=lambda item: item.created_at)
            chosen = candidates[0]
            claimed = build_claimed_job(
                chosen,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now=now,
                is_reclaim=chosen.state == "RUNNING",
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
        now = utc_now()
        with self._lock:
            job = require_job(self._jobs.get(job_id), job_id)
            assert_lease_ownership(job, worker_id=worker_id, fencing_token=fencing_token)
            updated = apply_heartbeat(job, extend_seconds=extend_seconds, now=now)
            self._jobs[job_id] = updated
            return updated

    def save_checkpoint(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        checkpoint_ref: str,
    ) -> ExecutionJob:
        now = utc_now()
        with self._lock:
            job = require_job(self._jobs.get(job_id), job_id)
            assert_lease_ownership(job, worker_id=worker_id, fencing_token=fencing_token)
            updated = apply_checkpoint(job, checkpoint_ref=checkpoint_ref, now=now)
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
        now = utc_now()
        with self._lock:
            job = require_job(self._jobs.get(job_id), job_id)
            assert_lease_ownership(job, worker_id=worker_id, fencing_token=fencing_token)
            updated = apply_completion(job, state=state, last_error=last_error, now=now)
            self._jobs[job_id] = updated
            return updated

    def request_cancellation(self, job_id: str) -> ExecutionJob:
        now = utc_now()
        with self._lock:
            job = require_job(self._jobs.get(job_id), job_id)
            updated = apply_cancel_request(job, now=now)
            self._jobs[job_id] = updated
            return updated

    def get_job(self, job_id: str) -> ExecutionJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_job_by_run_id(self, run_id: str) -> ExecutionJob | None:
        with self._lock:
            return next((job for job in self._jobs.values() if job.run_id == run_id), None)

    def list_jobs(
        self, tenant_id: str | None = None, state: JobState | None = None
    ) -> list[ExecutionJob]:
        with self._lock:
            return filter_jobs(list(self._jobs.values()), tenant_id=tenant_id, state=state)


from .file_job_repository import FileJobRepository
from .firestore_job_repository import FirestoreJobRepository

__all__ = [
    "FileJobRepository",
    "FirestoreJobRepository",
    "InMemoryJobRepository",
    "JobRepository",
]
