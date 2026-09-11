from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from .errors import JobFencingConflictError, JobLeaseLostError
from .job_models import ExecutionJob, JobCheckpoint
from .job_repository import JobRepository
from .runner import EvaluationRunner

logger = logging.getLogger(__name__)


class ExecutionJobWorker:
    """Durable worker that claims, executes, heartbeats, and completes ExecutionJobs."""

    def __init__(
        self,
        job_repository: JobRepository,
        runner: EvaluationRunner,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
        heartbeat_interval_seconds: float = 15.0,
    ) -> None:
        self._repo = job_repository
        self._runner = runner
        self._worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self._lease_seconds = lease_seconds
        self._heartbeat_interval = heartbeat_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def step(self) -> ExecutionJob | None:
        """Claims one job and processes it. Useful for tests and single-pass ticks."""
        job = self._repo.claim_job(self._worker_id, lease_seconds=self._lease_seconds)
        if not job:
            return None

        self._process_claimed_job(job)
        return self._repo.get_job(job.job_id)

    def _process_claimed_job(self, job: ExecutionJob) -> None:
        heartbeat_stop = threading.Event()
        fencing_token = job.fencing_token

        def _heartbeat_loop() -> None:
            while not heartbeat_stop.wait(self._heartbeat_interval):
                try:
                    self._repo.heartbeat(
                        job.job_id,
                        self._worker_id,
                        fencing_token,
                        extend_seconds=self._lease_seconds,
                    )
                except (JobLeaseLostError, JobFencingConflictError) as err:
                    logger.warning("Heartbeat failed for job %s: %s", job.job_id, err)
                    break
                except Exception as err:
                    logger.error("Unexpected heartbeat error for job %s: %s", job.job_id, err)

        hb_thread = threading.Thread(
            target=_heartbeat_loop,
            daemon=True,
            name=f"hb-{job.job_id}",
        )
        hb_thread.start()

        try:
            # Check if cancellation was requested before execution began
            current_job = self._repo.get_job(job.job_id)
            if current_job and current_job.cancel_requested_at:
                self._repo.complete_job(
                    job.job_id,
                    self._worker_id,
                    fencing_token,
                    state="CANCELLED",
                    last_error="Cancellation requested prior to start",
                )
                return

            # Execute run using EvaluationRunner
            # Checkpoint callback can be hooked into runner if needed
            run = self._runner.execute_run(job.run_id)

            # Determine final state based on run status
            final_state = "COMPLETED"
            if run.status == "FAILED":
                final_state = "FAILED"
            elif run.status == "CANCELLED":
                final_state = "CANCELLED"
            elif run.status == "PARTIAL":
                final_state = "PARTIAL"

            self._repo.complete_job(
                job.job_id,
                self._worker_id,
                fencing_token,
                state=final_state,
                last_error=run.error_message,
            )
        except (JobLeaseLostError, JobFencingConflictError) as lease_err:
            logger.warning(
                "Worker %s lost lease/fencing for job %s: %s",
                self._worker_id,
                job.job_id,
                lease_err,
            )
        except Exception as err:
            logger.exception("Failed to process job %s: %s", job.job_id, err)
            try:
                self._repo.complete_job(
                    job.job_id,
                    self._worker_id,
                    fencing_token,
                    state="FAILED",
                    last_error=str(err),
                )
            except Exception as complete_err:
                logger.error("Failed to mark job %s as FAILED: %s", job.job_id, complete_err)
        finally:
            heartbeat_stop.set()
            hb_thread.join(timeout=2.0)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()

        def _run_loop() -> None:
            while not self._stop_event.is_set():
                try:
                    job = self.step()
                    if not job:
                        self._stop_event.wait(1.0)
                except Exception as err:
                    logger.error("Worker error in loop: %s", err)
                    self._stop_event.wait(2.0)

        self._thread = threading.Thread(
            target=_run_loop,
            daemon=True,
            name=f"worker-{self._worker_id}",
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
