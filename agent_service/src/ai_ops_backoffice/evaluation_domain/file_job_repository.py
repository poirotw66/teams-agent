"""File-backed durable execution job repository with cross-process locking."""

from __future__ import annotations

import fcntl
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from .job_models import ExecutionJob, JobState
from .job_repository import InMemoryJobRepository
from .json_record_io import load_json_model


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
                job = load_json_model(path, ExecutionJob)
                if job is not None:
                    jobs[job.job_id] = job
            self._jobs = jobs

    def _write_record_atomic(self, job: ExecutionJob) -> None:
        target = self._records_dir / f"{job.job_id}.json"
        temp = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as f:
            f.write(job.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
        if sys.platform != "win32":
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

    def claim_job(self, worker_id: str, lease_seconds: float = 60.0) -> ExecutionJob | None:
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
