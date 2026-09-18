"""Claimed-job execution helpers for EvaluationJobWorker."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from .errors import JobFencingConflictError, JobLeaseLostError
from .job_models import ExecutionJob
from .job_repository import JobRepository

logger = logging.getLogger(__name__)


def start_heartbeat_thread(
    *,
    repo: JobRepository,
    job: ExecutionJob,
    worker_id: str,
    fencing_token: int,
    lease_seconds: float,
    heartbeat_interval: float,
    heartbeat_stop: threading.Event,
) -> threading.Thread:
    def _heartbeat_loop() -> None:
        while not heartbeat_stop.wait(heartbeat_interval):
            try:
                repo.heartbeat(
                    job.job_id,
                    worker_id,
                    fencing_token,
                    extend_seconds=lease_seconds,
                )
            except (JobLeaseLostError, JobFencingConflictError) as err:
                logger.warning("Heartbeat failed for job %s: %s", job.job_id, err)
                break
            except Exception as err:
                logger.error("Unexpected heartbeat error for job %s: %s", job.job_id, err)

    thread = threading.Thread(
        target=_heartbeat_loop,
        daemon=True,
        name=f"hb-{job.job_id}",
    )
    thread.start()
    return thread


def bind_runner_guards(
    *,
    runner: Any,
    repo: JobRepository,
    job: ExecutionJob,
    worker_id: str,
    fencing_token: int,
    lease_seconds: float,
) -> Callable[[], None]:
    def _lease_guard() -> None:
        repo.heartbeat(
            job.job_id,
            worker_id,
            fencing_token,
            extend_seconds=lease_seconds,
        )
        repo.save_checkpoint(
            job.job_id,
            worker_id,
            fencing_token,
            checkpoint_ref=f"{job.run_id}:running",
        )

    def _checkpoint_saver(checkpoint_ref: str) -> None:
        repo.save_checkpoint(
            job.job_id,
            worker_id,
            fencing_token,
            checkpoint_ref=checkpoint_ref,
        )

    if hasattr(runner, "bind_lease_guard"):
        runner.bind_lease_guard(_lease_guard)
    if hasattr(runner, "bind_checkpoint_saver"):
        runner.bind_checkpoint_saver(_checkpoint_saver)

    def _unbind() -> None:
        if hasattr(runner, "bind_lease_guard"):
            runner.bind_lease_guard(None)
        if hasattr(runner, "bind_checkpoint_saver"):
            runner.bind_checkpoint_saver(None)

    return _unbind


def final_state_for_run(run: Any) -> str:
    if run.status == "FAILED":
        return "FAILED"
    if run.status == "CANCELLED":
        return "CANCELLED"
    if run.status == "PARTIAL":
        return "PARTIAL"
    return "COMPLETED"


def complete_job_failed(
    *,
    repo: JobRepository,
    job: ExecutionJob,
    worker_id: str,
    fencing_token: int,
    error: Exception,
) -> None:
    try:
        repo.complete_job(
            job.job_id,
            worker_id,
            fencing_token,
            state="FAILED",
            last_error=str(error),
        )
    except Exception as complete_err:
        logger.error("Failed to mark job %s as FAILED: %s", job.job_id, complete_err)
