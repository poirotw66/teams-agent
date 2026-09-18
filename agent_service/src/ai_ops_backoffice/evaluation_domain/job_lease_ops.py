"""Shared lease, fencing, and serialization helpers for execution job repositories."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .errors import (
    EvaluationNotFoundError,
    JobFencingConflictError,
    JobLeaseLostError,
)
from .job_models import ExecutionJob, JobState

ACTIVE_OR_TERMINAL_STATES: frozenset[str] = frozenset(
    {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}
)
TERMINAL_STATES: frozenset[str] = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


def job_document_payload(job: ExecutionJob) -> dict[str, Any]:
    """Serialize an execution job for JSON/Firestore document storage."""
    return json.loads(job.model_dump_json())


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_job(job: ExecutionJob | None, job_id: str) -> ExecutionJob:
    if job is None:
        raise EvaluationNotFoundError(f"Job {job_id} not found")
    return job


def assert_lease_ownership(
    job: ExecutionJob,
    *,
    worker_id: str,
    fencing_token: int,
    strict_messages: bool = True,
) -> None:
    """Validate fencing token and lease owner before a mutating lease operation."""
    if job.fencing_token != fencing_token:
        if strict_messages:
            raise JobFencingConflictError(
                f"Fencing token mismatch for job {job.job_id}: "
                f"current={job.fencing_token}, worker={fencing_token}"
            )
        raise JobFencingConflictError(f"Fencing token conflict for job {job.job_id}")
    if job.lease_owner != worker_id:
        if strict_messages:
            raise JobLeaseLostError(
                f"Job {job.job_id} lease is owned by {job.lease_owner}, not {worker_id}"
            )
        raise JobLeaseLostError(f"Lease lost for job {job.job_id}")


def find_logical_key_duplicate(
    jobs: list[ExecutionJob], candidate: ExecutionJob
) -> ExecutionJob | None:
    """Return an existing active/terminal job that shares tenant + logical_key."""
    for existing in jobs:
        if (
            existing.tenant_id == candidate.tenant_id
            and existing.logical_key == candidate.logical_key
            and existing.state in ACTIVE_OR_TERMINAL_STATES
        ):
            return existing
    return None


def build_claimed_job(
    job: ExecutionJob,
    *,
    worker_id: str,
    lease_seconds: float,
    now: datetime,
    is_reclaim: bool,
) -> ExecutionJob:
    new_attempt = job.attempt + 1 if is_reclaim else job.attempt
    return job.model_copy(
        update={
            "state": "RUNNING",
            "lease_owner": worker_id,
            "lease_until": now + timedelta(seconds=lease_seconds),
            "heartbeat_at": now,
            "attempt": new_attempt,
            "fencing_token": job.fencing_token + 1,
            "revision": job.revision + 1,
            "updated_at": now,
        }
    )


def build_max_attempts_failed_job(job: ExecutionJob, *, now: datetime) -> ExecutionJob:
    return job.model_copy(
        update={
            "state": "FAILED",
            "last_error": "Lease expired and max attempts exceeded",
            "updated_at": now,
            "revision": job.revision + 1,
        }
    )


def apply_heartbeat(job: ExecutionJob, *, extend_seconds: float, now: datetime) -> ExecutionJob:
    return job.model_copy(
        update={
            "heartbeat_at": now,
            "lease_until": now + timedelta(seconds=extend_seconds),
            "updated_at": now,
            "revision": job.revision + 1,
        }
    )


def apply_checkpoint(job: ExecutionJob, *, checkpoint_ref: str, now: datetime) -> ExecutionJob:
    return job.model_copy(
        update={
            "checkpoint_ref": checkpoint_ref,
            "heartbeat_at": now,
            "updated_at": now,
            "revision": job.revision + 1,
        }
    )


def apply_completion(
    job: ExecutionJob,
    *,
    state: JobState,
    last_error: str | None,
    now: datetime,
) -> ExecutionJob:
    return job.model_copy(
        update={
            "state": state,
            "lease_owner": None,
            "lease_until": None,
            "last_error": last_error or job.last_error,
            "updated_at": now,
            "revision": job.revision + 1,
        }
    )


def apply_cancel_request(job: ExecutionJob, *, now: datetime) -> ExecutionJob:
    if job.state in TERMINAL_STATES:
        return job
    return job.model_copy(
        update={
            "cancel_requested_at": now,
            "updated_at": now,
            "revision": job.revision + 1,
        }
    )


def filter_jobs(
    jobs: list[ExecutionJob],
    *,
    tenant_id: str | None = None,
    state: JobState | None = None,
) -> list[ExecutionJob]:
    results = list(jobs)
    if tenant_id:
        results = [job for job in results if job.tenant_id == tenant_id]
    if state:
        results = [job for job in results if job.state == state]
    return sorted(results, key=lambda job: job.created_at, reverse=True)


__all__ = [
    "ACTIVE_OR_TERMINAL_STATES",
    "TERMINAL_STATES",
    "apply_cancel_request",
    "apply_checkpoint",
    "apply_completion",
    "apply_heartbeat",
    "assert_lease_ownership",
    "build_claimed_job",
    "build_max_attempts_failed_job",
    "filter_jobs",
    "find_logical_key_duplicate",
    "job_document_payload",
    "require_job",
    "utc_now",
]
