"""Transactional outbox dispatch and recovery for evaluation runs."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .job_models import ExecutionJob
from .job_repository import JobRepository
from .repository import EvaluationRepository

logger = logging.getLogger(__name__)

__all__ = [
    "dispatch_outbox_job",
    "mark_run_enqueue_failed",
    "recover_undispatched_runs",
    "remove_outbox_job",
]


def _parse_created_at(raw_created: Any) -> datetime:
    if isinstance(raw_created, str):
        try:
            return datetime.fromisoformat(raw_created)
        except Exception:
            return datetime.now(timezone.utc)
    if isinstance(raw_created, datetime):
        return raw_created
    return datetime.now(timezone.utc)


def dispatch_outbox_job(
    job_repo: JobRepository | None,
    outbox_entry: dict[str, Any],
) -> bool:
    if not job_repo:
        return False
    created_dt = _parse_created_at(outbox_entry.get("created_at"))
    job = ExecutionJob(
        tenant_id=str(outbox_entry.get("tenant_id", "default")),
        job_id=str(outbox_entry["job_id"]),
        run_id=str(outbox_entry["run_id"]),
        logical_key=str(outbox_entry.get("logical_key", f"run:{outbox_entry['run_id']}")),
        state="QUEUED",
        created_at=created_dt,
        updated_at=datetime.now(timezone.utc),
    )
    try:
        job_repo.enqueue_job(job)
        return True
    except Exception:
        return False


def remove_outbox_job(repo: EvaluationRepository, outbox_id: str) -> None:
    try:
        if hasattr(repo, "delete_outbox_jobs"):
            repo.delete_outbox_jobs([outbox_id])
            return
        cur_state = repo.load()
        remaining = [
            job
            for job in getattr(cur_state, "outbox_jobs", ())
            if job.get("outbox_id") != outbox_id and job.get("job_id") != outbox_id
        ]
        repo.commit_mutation(
            cur_state.model_copy(update={"outbox_jobs": tuple(remaining)}),
            expected_revision=cur_state.revision,
        )
    except Exception as err:
        logger.warning("Failed to remove dispatched outbox job %s: %s", outbox_id, err)


def mark_run_enqueue_failed(repo: EvaluationRepository, run_id: str, error: str) -> None:
    state = repo.load()
    run = next((item for item in state.runs if item.run_id == run_id), None)
    if not run:
        return
    failed = run.model_copy(
        update={
            "status": "FAILED",
            "cancel_reason": f"job_enqueue_failed: {error}",
            "completed_at": datetime.now(timezone.utc),
        }
    )
    runs = [item for item in state.runs if item.run_id != run_id] + [failed]
    repo.commit_mutation(
        state.model_copy(update={"runs": tuple(runs)}),
        expected_revision=state.revision,
    )


def _drain_outbox_jobs(
    repo: EvaluationRepository,
    job_repo: JobRepository,
) -> int:
    state = repo.load()
    outbox_jobs = list(getattr(state, "outbox_jobs", ()))
    dispatched_ids: set[str] = set()
    recovered = 0

    for outbox_job in outbox_jobs:
        oid = str(outbox_job.get("outbox_id", outbox_job.get("job_id")))
        if dispatch_outbox_job(job_repo, outbox_job):
            dispatched_ids.add(oid)
            recovered += 1

    if not dispatched_ids:
        return recovered

    try:
        if hasattr(repo, "delete_outbox_jobs"):
            repo.delete_outbox_jobs(dispatched_ids)
        else:
            cur_state = repo.load()
            remaining = [
                job
                for job in getattr(cur_state, "outbox_jobs", ())
                if str(job.get("outbox_id", job.get("job_id"))) not in dispatched_ids
            ]
            repo.commit_mutation(
                cur_state.model_copy(update={"outbox_jobs": tuple(remaining)}),
                expected_revision=cur_state.revision,
            )
    except Exception as err:
        logger.warning("Failed to remove dispatched outbox jobs during recovery: %s", err)
    return recovered


def _recover_legacy_queued_runs(
    repo: EvaluationRepository,
    job_repo: JobRepository,
    *,
    older_than_seconds: float,
    now: datetime,
) -> int:
    recovered = 0
    for run in repo.list_runs():
        if run.status != "QUEUED":
            continue
        age = (now - run.created_at).total_seconds()
        if age < older_than_seconds:
            continue
        existing = job_repo.get_job_by_run_id(run.run_id)
        if existing is not None and existing.state in {"QUEUED", "RUNNING"}:
            continue
        job = ExecutionJob(
            tenant_id=run.tenant_id,
            job_id=str(uuid.uuid4()),
            run_id=run.run_id,
            logical_key=f"run:{run.tenant_id}:{run.run_id}",
            state="QUEUED",
            created_at=now,
            updated_at=now,
        )
        try:
            job_repo.enqueue_job(job)
            recovered += 1
        except Exception as err:
            logger.debug("Failed to recover job for run %s: %s", run.run_id, err)
    return recovered


def recover_undispatched_runs(
    repo: EvaluationRepository,
    job_repo: JobRepository | None,
    *,
    older_than_seconds: float = 30.0,
) -> int:
    """Process pending outbox jobs and recover queued runs missing durable jobs."""
    if not job_repo:
        return 0
    now = datetime.now(timezone.utc)
    recovered = _drain_outbox_jobs(repo, job_repo)
    recovered += _recover_legacy_queued_runs(
        repo,
        job_repo,
        older_than_seconds=older_than_seconds,
        now=now,
    )
    return recovered
