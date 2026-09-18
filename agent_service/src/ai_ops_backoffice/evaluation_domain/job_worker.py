from __future__ import annotations

import logging
import threading
from typing import Any
from uuid import uuid4

from .errors import JobFencingConflictError, JobLeaseLostError
from .job_models import ExecutionJob
from .job_repository import JobRepository
from .job_worker_process import (
    bind_runner_guards,
    complete_job_failed,
    final_state_for_run,
    start_heartbeat_thread,
)
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
        run_service: Any | None = None,
    ) -> None:
        self._repo = job_repository
        self._runner = runner
        self._worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self._lease_seconds = lease_seconds
        self._heartbeat_interval = heartbeat_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_service = run_service

    def set_run_service(self, run_service: Any | None) -> None:
        """Attach EvaluationRunService after construction (create_app wiring order)."""
        self._run_service = run_service

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
        hb_thread = start_heartbeat_thread(
            repo=self._repo,
            job=job,
            worker_id=self._worker_id,
            fencing_token=fencing_token,
            lease_seconds=self._lease_seconds,
            heartbeat_interval=self._heartbeat_interval,
            heartbeat_stop=heartbeat_stop,
        )
        try:
            self._execute_claimed_job(job, fencing_token)
        except (JobLeaseLostError, JobFencingConflictError) as lease_err:
            logger.warning(
                "Worker %s lost lease/fencing for job %s: %s",
                self._worker_id,
                job.job_id,
                lease_err,
            )
        except Exception as err:
            logger.exception("Failed to process job %s", job.job_id)
            complete_job_failed(
                repo=self._repo,
                job=job,
                worker_id=self._worker_id,
                fencing_token=fencing_token,
                error=err,
            )
        finally:
            heartbeat_stop.set()
            hb_thread.join(timeout=2.0)

    def _execute_claimed_job(self, job: ExecutionJob, fencing_token: int) -> None:
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

        unbind = bind_runner_guards(
            runner=self._runner,
            repo=self._repo,
            job=job,
            worker_id=self._worker_id,
            fencing_token=fencing_token,
            lease_seconds=self._lease_seconds,
        )
        try:
            self._repo.save_checkpoint(
                job.job_id,
                self._worker_id,
                fencing_token,
                checkpoint_ref=f"{job.run_id}:started",
            )
            run = self._runner.execute_run(job.run_id)
        finally:
            unbind()

        self._repo.complete_job(
            job.job_id,
            self._worker_id,
            fencing_token,
            state=final_state_for_run(run),
            last_error=run.error_message,
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()

        def _run_loop() -> None:
            while not self._stop_event.is_set():
                try:
                    if self._run_service is not None and hasattr(
                        self._run_service, "recover_undispatched_runs"
                    ):
                        self._run_service.recover_undispatched_runs()
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
