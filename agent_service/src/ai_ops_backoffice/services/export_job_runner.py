"""Claimed export job execution mixin: encode, lease renew, complete, fail/requeue."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any

from operations_core.access import ActorContext
from operations_core.audit_errors import AuditWriteError
from operations_core.contracts import utc_now

from .export_format import flatten_for_csv, flatten_for_xlsx
from .export_models import ExportJob, deserialize_export_job, serialize_export_job

__all__ = [
    "ExportJobRunnerMixin",
    "encode_export_payload",
]


def encode_export_payload(job: ExportJob, result: dict[str, Any]) -> tuple[bytes, str]:
    if job.export_format == "csv":
        return flatten_for_csv(result).encode("utf-8-sig"), "text/csv; charset=utf-8"
    if job.export_format == "xlsx":
        return (
            flatten_for_xlsx(result),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return (
        json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json; charset=utf-8",
    )


class ExportJobRunnerMixin:
    """Lease-aware claimed-job runner for ``ExportJobService``."""

    async def _renew_lease_until_stopped(
        self,
        *,
        job_id: str,
        lease_token: str,
        stop_renew: asyncio.Event,
    ) -> None:
        while not stop_renew.is_set():
            try:
                await asyncio.wait_for(stop_renew.wait(), timeout=max(5, self._lease_seconds // 3))
                return
            except TimeoutError:
                ok = await self._job_store.renew_lease(
                    job_id,
                    worker_id=self._worker_id,
                    lease_token=lease_token,
                    lease_seconds=self._lease_seconds,
                    now=utc_now(),
                )
                if not ok:
                    return

    async def _commit_export_success(
        self,
        *,
        actor: ActorContext,
        job: ExportJob,
        job_id: str,
        lease_token: str,
        result: dict[str, Any],
    ) -> None:
        metadata = result.get("exportMetadata") or {}
        record_count = metadata.get("recordCount")
        if isinstance(record_count, int) and record_count > self._max_records:
            raise ValueError(f"Export exceeds the maximum of {self._max_records} records.")
        content, content_type = encode_export_payload(job, result)
        # Track pending artifact before audit/persist so failure paths can
        # delete it even when job.content_ref was never committed.
        content_ref = await self._content_store.put(
            job_id=job_id,
            content=content,
            content_type=content_type,
            attempt=job.attempt_count,
            lease_token=lease_token,
        )
        self._pending_content_refs.add(content_ref)
        try:
            await self._audit(
                actor,
                "export.complete",
                job_id,
                after={
                    "exportType": job.export_type,
                    "exportFormat": job.export_format,
                    "status": "COMPLETED",
                    "attemptCount": job.attempt_count,
                    "recordCount": metadata.get("recordCount"),
                    "fields": metadata.get("fields") or [],
                    "queryFilters": metadata.get("queryFilters") or {},
                    "workerId": self._worker_id,
                },
            )
            job.status = "COMPLETED"
            job.result = result
            job.content_ref = content_ref
            job.content_type = content_type
            job.download_content = None
            job.download_bytes = None
            job.completed_at = utc_now().isoformat()
            job.error = None
            committed = await self._job_store.complete_if_owner(
                job_id,
                worker_id=self._worker_id,
                lease_token=lease_token,
                payload=serialize_export_job(job),
            )
            if not committed:
                # Lost lease mid-flight — another worker owns the job; drop orphan.
                await self._content_store.delete(content_ref=content_ref)
                return
            self._jobs[job_id] = job
        except Exception:
            await self._content_store.delete(content_ref=content_ref)
            raise
        finally:
            self._pending_content_refs.discard(content_ref)

    async def _audit_export_failure(
        self,
        *,
        job: ExportJob,
        job_id: str,
        retryable: bool,
        exc: BaseException,
    ) -> None:
        try:
            await self._audit(
                ActorContext(
                    user_id=job.requested_by,
                    display_name=job.requested_by,
                    role=job.requested_role,  # type: ignore[arg-type]
                    owner_unit_ids=job.requested_owner_units,
                    tenant_id=job.tenant_id,
                ),
                "export.failed" if not retryable else "export.retry",
                job_id,
                after={
                    "exportType": job.export_type,
                    "exportFormat": job.export_format,
                    "status": "QUEUED" if retryable else "FAILED",
                    "attemptCount": job.attempt_count,
                    "errorType": type(exc).__name__,
                    "workerId": self._worker_id,
                },
            )
        except AuditWriteError:
            pass

    async def _fail_or_requeue_export(
        self,
        *,
        job: ExportJob,
        job_id: str,
        lease_token: str,
        exc: BaseException,
        pending_content_ref: str | None,
    ) -> None:
        current = self._jobs.get(job_id) or job
        if pending_content_ref:
            await self._content_store.delete(content_ref=pending_content_ref)
            self._pending_content_refs.discard(pending_content_ref)
        if current.content_ref and current.content_ref != pending_content_ref:
            await self._content_store.delete(content_ref=current.content_ref)
        retryable = current.attempt_count < current.max_attempts and isinstance(
            exc, (TimeoutError, ConnectionError, OSError)
        )
        await self._audit_export_failure(job=job, job_id=job_id, retryable=retryable, exc=exc)
        if retryable:
            current.status = "QUEUED"
            current.error = str(exc)
            current.lease_owner = None
            current.lease_expires_at = None
            current.lease_token = None
            current.content_ref = None
            current.content_type = None
            committed = await self._job_store.requeue_if_owner(
                job_id,
                worker_id=self._worker_id,
                lease_token=lease_token,
                payload=serialize_export_job(current),
            )
            if not committed:
                return
            self._jobs[job_id] = current
            self._schedule(self._run_job(job_id))
            return
        current.status = "FAILED"
        current.error = str(exc)
        current.completed_at = utc_now().isoformat()
        current.content_ref = None
        current.content_type = None
        committed = await self._job_store.complete_if_owner(
            job_id,
            worker_id=self._worker_id,
            lease_token=lease_token,
            payload=serialize_export_job(current),
        )
        if committed:
            self._jobs[job_id] = current

    async def _run_job(self, job_id: str) -> None:
        claimed_payload = await self._job_store.claim_job(
            job_id,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
            now=utc_now(),
        )
        if claimed_payload is None:
            return
        job = deserialize_export_job(claimed_payload)
        lease_token = job.lease_token or ""
        self._jobs[job_id] = job
        renew_task: asyncio.Task[None] | None = None
        stop_renew = asyncio.Event()
        try:
            renew_task = asyncio.create_task(
                self._renew_lease_until_stopped(
                    job_id=job_id, lease_token=lease_token, stop_renew=stop_renew
                )
            )
            actor = await self._resolve_worker_actor(job)
            result = await self._execute(actor=actor, job=job)
            await self._commit_export_success(
                actor=actor,
                job=job,
                job_id=job_id,
                lease_token=lease_token,
                result=result,
            )
        except Exception as exc:  # noqa: BLE001
            await self._fail_or_requeue_export(
                job=job,
                job_id=job_id,
                lease_token=lease_token,
                exc=exc,
                pending_content_ref=None,
            )
        finally:
            stop_renew.set()
            if renew_task is not None:
                renew_task.cancel()
                with suppress(asyncio.CancelledError):
                    await renew_task
