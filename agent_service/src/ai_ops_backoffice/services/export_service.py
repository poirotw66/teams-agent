from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import AuditStore, build_audit_event
from agent_service.operations.audit_errors import AuditWriteError
from agent_service.operations.contracts import utc_now

from .export_authorization import (
    ExportAuthorizationError,
    ExportAuthorizationResolver,
    RoleRevalidatingExportAuthorizationResolver,
    require_current_export_access,
    tenant_for_actor,
)
from .export_content import ExportContentStore, FileExportContentStore
from .export_format import flatten_for_csv, flatten_for_xlsx
from .export_job_store import ExportJobStore, FileExportJobStore

ExportJobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "EXPIRED"]


@dataclass
class ExportJob:
    job_id: str
    export_type: str
    export_format: str
    status: ExportJobStatus
    reason: str
    requested_by: str
    requested_role: str
    days: int
    created_at: str
    expires_at: str
    tenant_id: str = "local-development"
    requested_owner_units: tuple[str, ...] = ()
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    download_content: str | None = None
    download_bytes: bytes | None = None
    content_ref: str | None = None
    content_type: str | None = None
    error: str | None = None


class ExportJobService:
    def __init__(
        self,
        *,
        audit_store: AuditStore,
        store_path: Path,
        environment: str,
        job_store: ExportJobStore | None = None,
        content_store: ExportContentStore | None = None,
        ttl_seconds: int = 86400,
        max_records: int = 100_000,
        authorization_resolver: ExportAuthorizationResolver | None = None,
        run_inline: bool = False,
    ) -> None:
        self._audit_store = audit_store
        self._store_path = store_path
        self._environment = environment
        self._ttl_seconds = ttl_seconds
        self._max_records = max_records
        self._jobs: dict[str, ExportJob] = {}
        self._lock = asyncio.Lock()
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._job_store = job_store or FileExportJobStore(self._store_path)
        self._content_store = content_store or FileExportContentStore(
            self._store_path / "content"
        )
        self._authorization_resolver = (
            authorization_resolver or RoleRevalidatingExportAuthorizationResolver()
        )
        self._run_inline = run_inline
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def _persist(self, job: ExportJob) -> None:
        await self._job_store.put(job.job_id, self._serialize_job(job))

    def _serialize_job(self, job: ExportJob) -> dict[str, Any]:
        payload = job.__dict__.copy()
        download_bytes = payload.pop("download_bytes", None)
        if download_bytes is not None:
            payload["download_bytes_b64"] = base64.b64encode(download_bytes).decode("ascii")
        payload["requested_owner_units"] = list(job.requested_owner_units)
        return payload

    def _deserialize_job(self, item: dict[str, Any]) -> ExportJob:
        defaults = {
            "export_format": "json",
            "download_content": None,
            "download_bytes": None,
            "content_ref": None,
            "content_type": None,
            "tenant_id": "local-development",
            "requested_owner_units": (),
        }
        merged = {**defaults, **item}
        for key in ("created_at", "expires_at", "completed_at"):
            if isinstance(merged.get(key), datetime):
                merged[key] = merged[key].isoformat()
        encoded = merged.pop("download_bytes_b64", None)
        if encoded:
            merged["download_bytes"] = base64.b64decode(encoded)
        units = merged.get("requested_owner_units") or ()
        merged["requested_owner_units"] = tuple(units)
        return ExportJob(**merged)

    def _schedule(self, coroutine: Coroutine[Any, Any, None]) -> None:
        if self._run_inline:
            task = asyncio.get_running_loop().create_task(coroutine)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def wait_for_background_tasks(self) -> None:
        pending = list(self._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def create_job(
        self,
        *,
        actor: ActorContext,
        export_type: str,
        reason: str,
        days: int,
        runner: Callable[[], Coroutine[Any, Any, dict[str, Any]]],
        export_format: str = "json",
        request_metadata: dict[str, object] | None = None,
    ) -> ExportJob:
        job_id = str(uuid.uuid4())
        now = utc_now()
        tenant_id = tenant_for_actor(actor, environment=self._environment)
        register = getattr(self._authorization_resolver, "register", None)
        if callable(register):
            register(actor=actor, tenant_id=tenant_id)
        job = ExportJob(
            job_id=job_id,
            export_type=export_type,
            export_format=export_format,
            status="QUEUED",
            reason=reason,
            requested_by=actor.user_id,
            requested_role=actor.role,
            days=days,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self._ttl_seconds)).isoformat(),
            tenant_id=tenant_id,
            requested_owner_units=tuple(actor.owner_unit_ids),
        )
        async with self._lock:
            self._jobs[job_id] = job
            await self._persist(job)
        try:
            await self._audit(
                actor,
                "export.create",
                job_id,
                reason=reason,
                after={
                    "exportType": export_type,
                    "exportFormat": export_format,
                    "days": days,
                    "tenantId": tenant_id,
                    **(request_metadata or {}),
                },
            )
        except AuditWriteError:
            async with self._lock:
                self._jobs.pop(job_id, None)
                await self._job_store.delete(job_id)
            raise
        self._schedule(self._run_job(job_id, runner))
        return job

    async def _resolve_worker_actor(self, job: ExportJob) -> ActorContext:
        actor = await self._authorization_resolver.resolve(
            requester_id=job.requested_by,
            tenant_id=job.tenant_id,
        )
        if actor is None:
            raise ExportAuthorizationError("Export requester is no longer resolvable.")
        require_current_export_access(
            actor=actor,
            requester_id=job.requested_by,
            tenant_id=job.tenant_id,
            requested_owner_units=job.requested_owner_units,
            environment=self._environment,
        )
        return actor

    async def _run_job(
        self,
        job_id: str,
        runner: Callable[[], Coroutine[Any, Any, dict[str, Any]]],
    ) -> None:
        async with self._lock:
            job = self._jobs[job_id]
            job.status = "RUNNING"
            await self._persist(job)
        try:
            actor = await self._resolve_worker_actor(job)
            result = await runner()
            metadata = result.get("exportMetadata") or {}
            record_count = metadata.get("recordCount")
            if isinstance(record_count, int) and record_count > self._max_records:
                raise ValueError(
                    f"Export exceeds the maximum of {self._max_records} records."
                )
            if job.export_format == "csv":
                content = flatten_for_csv(result).encode("utf-8-sig")
                content_type = "text/csv; charset=utf-8"
            elif job.export_format == "xlsx":
                content = flatten_for_xlsx(result)
                content_type = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                content = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            content_ref = await self._content_store.put(
                job_id=job_id,
                content=content,
                content_type=content_type,
            )
            await self._audit(
                actor,
                "export.complete",
                job_id,
                after={
                    "exportType": job.export_type,
                    "exportFormat": job.export_format,
                    "status": "COMPLETED",
                    "recordCount": metadata.get("recordCount"),
                    "fields": metadata.get("fields") or [],
                    "queryFilters": metadata.get("queryFilters") or {},
                },
            )
            async with self._lock:
                job = self._jobs[job_id]
                job.status = "COMPLETED"
                job.result = result
                job.content_ref = content_ref
                job.content_type = content_type
                job.download_content = None
                job.download_bytes = None
                job.completed_at = utc_now().isoformat()
                await self._persist(job)
        except Exception as exc:  # noqa: BLE001
            current = self._jobs.get(job_id)
            if current and current.content_ref:
                await self._content_store.delete(content_ref=current.content_ref)
            try:
                await self._audit(
                    ActorContext(
                        user_id=job.requested_by,
                        display_name=job.requested_by,
                        role=job.requested_role,  # type: ignore[arg-type]
                        owner_unit_ids=job.requested_owner_units,
                    ),
                    "export.failed",
                    job_id,
                    after={
                        "exportType": job.export_type,
                        "exportFormat": job.export_format,
                        "status": "FAILED",
                        "errorType": type(exc).__name__,
                    },
                )
            except AuditWriteError:
                pass
            async with self._lock:
                job = self._jobs[job_id]
                job.status = "FAILED"
                job.error = str(exc)
                job.completed_at = utc_now().isoformat()
                job.content_ref = None
                job.content_type = None
                await self._persist(job)

    async def get_job(self, job_id: str, *, actor: ActorContext) -> ExportJob | None:
        async with self._lock:
            persisted = await self._job_store.get(job_id)
            job = self._deserialize_job(persisted) if persisted is not None else self._jobs.get(job_id)
            if job is None:
                return None
            self._jobs[job_id] = job
            expires_at = datetime.fromisoformat(job.expires_at.replace("Z", "+00:00"))
            if job.status == "COMPLETED" and utc_now() > expires_at:
                await self._expire_job(job)
            try:
                require_current_export_access(
                    actor=actor,
                    requester_id=job.requested_by,
                    tenant_id=job.tenant_id,
                    requested_owner_units=job.requested_owner_units,
                    environment=self._environment,
                )
            except ExportAuthorizationError:
                return None
            return job

    async def _expire_job(self, job: ExportJob) -> None:
        if job.content_ref:
            await self._content_store.delete(content_ref=job.content_ref)
        job.status = "EXPIRED"
        job.result = None
        job.content_ref = None
        job.content_type = None
        job.download_content = None
        job.download_bytes = None
        await self._persist(job)

    async def purge_expired_jobs(self) -> int:
        expired_payloads = await self._job_store.list_expired(utc_now())
        removed = 0
        async with self._lock:
            for payload in expired_payloads:
                job = self._deserialize_job(payload)
                await self._expire_job(job)
                self._jobs[job.job_id] = job
                removed += 1
        return removed

    async def get_content(self, job: ExportJob) -> tuple[bytes, str] | None:
        if job.content_ref:
            content = await self._content_store.get(content_ref=job.content_ref)
            if content is not None:
                return content, job.content_type or "application/octet-stream"
        if job.download_bytes is not None:
            return job.download_bytes, "application/octet-stream"
        if job.download_content is not None:
            return job.download_content.encode("utf-8"), job.content_type or "text/plain"
        return None

    async def record_download(self, job_id: str, *, actor: ActorContext) -> None:
        await self._audit(actor, "export.download", job_id)

    async def _audit(
        self,
        actor: ActorContext,
        action: str,
        job_id: str,
        *,
        after: dict[str, object] | None = None,
        reason: str | None = None,
    ) -> None:
        try:
            await self._audit_store.append(
                build_audit_event(
                    actor_id=actor.user_id,
                    actor_role=actor.role,
                    action=action,
                    target_type="export_job",
                    target_id=job_id,
                    after=after,
                    reason=reason,
                    environment=self._environment,
                )
            )
        except Exception as exc:
            raise AuditWriteError(f"Audit write failed for {action}.") from exc
