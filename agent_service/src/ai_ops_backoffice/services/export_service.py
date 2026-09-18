"""Export job orchestration: create, recover, authorize, download, and lifecycle."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from operations_core.access import ActorContext
from operations_core.audit import AuditStore, build_audit_event
from operations_core.audit_errors import AuditWriteError
from operations_core.contracts import utc_now

from .export_artifact_gc import ExportArtifactGcMixin
from .export_auth_store import FileBackedExportAuthorizationResolver
from .export_authorization import (
    ExportAuthoritySource,
    ExportAuthorizationError,
    ExportAuthorizationResolver,
    ExportIdempotencyConflictError,
    UnavailableExportAuthorizationResolver,
    require_current_export_access,
    tenant_for_actor,
)
from .export_content import ExportContentStore, FileExportContentStore
from .export_job_runner import ExportJobRunnerMixin
from .export_job_store import ExportJobStore, FileExportJobStore
from .export_models import (
    LEASE_SECONDS,
    RECOVERY_SCAN_SECONDS,
    ExportJob,
    ExportJobStatus,
    deserialize_export_job,
    export_request_fingerprint,
    serialize_export_job,
)

# Compatibility re-exports for callers that import the job contract from this module.
__all__ = [
    "LEASE_SECONDS",
    "RECOVERY_SCAN_SECONDS",
    "ExportExecutionBackend",
    "ExportJob",
    "ExportJobService",
    "ExportJobStatus",
    "export_request_fingerprint",
]


class ExportExecutionBackend(Protocol):
    """Rebuild export work from persisted job parameters with a fresh actor."""

    async def execute(self, *, actor: ActorContext, job: ExportJob) -> dict[str, Any]: ...


class ExportJobService(ExportJobRunnerMixin, ExportArtifactGcMixin):
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
        export_authority: ExportAuthoritySource | None = None,
        require_export_authority: bool | None = None,
        execution_backend: ExportExecutionBackend | None = None,
        worker_id: str | None = None,
        run_inline: bool = False,
        lease_seconds: int = LEASE_SECONDS,
        recovery_scan_seconds: int = RECOVERY_SCAN_SECONDS,
    ) -> None:
        self._audit_store = audit_store
        self.store_path = store_path
        self._environment = environment
        self._ttl_seconds = ttl_seconds
        self._max_records = max_records
        self._jobs: dict[str, ExportJob] = {}
        self._lock = asyncio.Lock()
        self.store_path.mkdir(parents=True, exist_ok=True)
        self._job_store = job_store or FileExportJobStore(self.store_path)
        self._content_store = content_store or FileExportContentStore(self.store_path / "content")
        self._authorization_resolver = self._build_authorization_resolver(
            authorization_resolver=authorization_resolver,
            export_authority=export_authority,
            require_export_authority=require_export_authority,
            environment=environment,
        )
        self._execution_backend = execution_backend
        self._legacy_runners: dict[str, Callable[[], Coroutine[Any, Any, dict[str, Any]]]] = {}
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._run_inline = run_inline
        self._lease_seconds = lease_seconds
        self._recovery_scan_seconds = recovery_scan_seconds
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._pending_content_refs: set[str] = set()

    def _build_authorization_resolver(
        self,
        *,
        authorization_resolver: ExportAuthorizationResolver | None,
        export_authority: ExportAuthoritySource | None,
        require_export_authority: bool | None,
        environment: str,
    ) -> ExportAuthorizationResolver:
        lab_environment = environment.lower() in {"dev", "test", "poc", "lab"}
        if require_export_authority is None:
            require_export_authority = not lab_environment
        if authorization_resolver is not None:
            return authorization_resolver
        if require_export_authority and export_authority is None:
            # Production must not silently accept file-registry-only revoke checks.
            return UnavailableExportAuthorizationResolver()
        return FileBackedExportAuthorizationResolver(
            self.store_path / "export_auth_registry.json",
            authority=export_authority,
        )

    def configure_authorization_resolver(
        self,
        resolver: ExportAuthorizationResolver,
    ) -> None:
        self._authorization_resolver = resolver

    def configure_execution_backend(self, backend: ExportExecutionBackend) -> None:
        self._execution_backend = backend

    async def _persist(self, job: ExportJob) -> None:
        await self._job_store.put(job.job_id, serialize_export_job(job))

    def _schedule(self, coroutine: Coroutine[Any, Any, None]) -> None:
        if self._run_inline:
            # Tests / single-process: still schedule on the loop when available.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(coroutine)
                return
            task = loop.create_task(coroutine)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def wait_for_background_tasks(self) -> None:
        pending = list(self._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _lookup_idempotent_job(
        self,
        *,
        idempotency_key: str,
        tenant_id: str,
        requester_id: str,
        fingerprint: str,
    ) -> ExportJob | None:
        existing_payload = await self._job_store.find_by_idempotency_scope(
            key=idempotency_key,
            tenant_id=tenant_id,
            requester_id=requester_id,
        )
        if existing_payload is None:
            return None
        existing = deserialize_export_job(existing_payload)
        if existing.request_fingerprint and existing.request_fingerprint != fingerprint:
            raise ExportIdempotencyConflictError(
                "Idempotency key was reused with different export parameters."
            )
        self._jobs[existing.job_id] = existing
        return existing

    def _build_queued_job(
        self,
        *,
        actor: ActorContext,
        export_type: str,
        reason: str,
        days: int,
        request_params: dict[str, Any] | None,
        export_format: str,
        idempotency_key: str | None,
        tenant_id: str,
        fingerprint: str,
    ) -> ExportJob:
        now = utc_now()
        register = getattr(self._authorization_resolver, "register", None)
        if callable(register):
            register(actor=actor, tenant_id=tenant_id)
        return ExportJob(
            job_id=str(uuid.uuid4()),
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
            request_params=dict(request_params or {}),
            request_fingerprint=fingerprint,
            idempotency_key=idempotency_key,
        )

    async def create_job(
        self,
        *,
        actor: ActorContext,
        export_type: str,
        reason: str,
        days: int,
        request_params: dict[str, Any] | None = None,
        export_format: str = "json",
        idempotency_key: str | None = None,
        request_metadata: dict[str, object] | None = None,
        runner: Callable[[], Coroutine[Any, Any, dict[str, Any]]] | None = None,
    ) -> ExportJob:
        tenant_id = tenant_for_actor(actor, environment=self._environment)
        fingerprint = export_request_fingerprint(
            export_type=export_type,
            export_format=export_format,
            days=days,
            reason=reason,
            request_params=request_params,
        )
        if idempotency_key:
            existing = await self._lookup_idempotent_job(
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
                requester_id=actor.user_id,
                fingerprint=fingerprint,
            )
            if existing is not None:
                return existing
        job = self._build_queued_job(
            actor=actor,
            export_type=export_type,
            reason=reason,
            days=days,
            request_params=request_params,
            export_format=export_format,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            fingerprint=fingerprint,
        )
        async with self._lock:
            self._jobs[job.job_id] = job
            if runner is not None:
                self._legacy_runners[job.job_id] = runner
            await self._persist(job)
        try:
            await self._audit(
                actor,
                "export.create",
                job.job_id,
                reason=reason,
                after={
                    "exportType": export_type,
                    "exportFormat": export_format,
                    "days": days,
                    "tenantId": tenant_id,
                    "idempotencyKey": idempotency_key,
                    "requestFingerprint": fingerprint,
                    **(request_metadata or {}),
                },
            )
        except AuditWriteError:
            async with self._lock:
                self._jobs.pop(job.job_id, None)
                self._legacy_runners.pop(job.job_id, None)
                await self._job_store.delete(job.job_id)
            raise
        self._schedule(self._run_job(job.job_id))
        return job

    async def recover_interrupted_jobs(self) -> int:
        """Schedule claim attempts for QUEUED / apparently-expired RUNNING jobs.

        Never rewrite status from a stale list snapshot. ``claim_job`` atomically
        takes over only when the durable record is still QUEUED or still expired;
        if another worker already holds a fresh lease, claim is a no-op.
        """
        payloads = await self._job_store.list_by_status({"QUEUED", "RUNNING"})
        recovered = 0
        now = utc_now()
        for payload in payloads:
            job = deserialize_export_job(payload)
            if job.status == "RUNNING":
                lease_raw = job.lease_expires_at
                if lease_raw:
                    lease_expires = datetime.fromisoformat(lease_raw.replace("Z", "+00:00"))
                    if lease_expires > now:
                        continue
            self._jobs[job.job_id] = job
            self._schedule(self._run_job(job.job_id))
            recovered += 1
        return recovered

    async def run_recovery_scanner(self, stop_event: asyncio.Event) -> None:
        """Periodically take over expired leases (not only at process start)."""
        while not stop_event.is_set():
            try:
                await self.recover_interrupted_jobs()
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._recovery_scan_seconds)
            except TimeoutError:
                continue

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

    async def _execute(self, *, actor: ActorContext, job: ExportJob) -> dict[str, Any]:
        legacy = self._legacy_runners.pop(job.job_id, None)
        if legacy is not None:
            return await legacy()
        if self._execution_backend is None:
            raise RuntimeError("Export execution backend is not configured.")
        return await self._execution_backend.execute(actor=actor, job=job)

    async def get_job(self, job_id: str, *, actor: ActorContext) -> ExportJob | None:
        async with self._lock:
            persisted = await self._job_store.get(job_id)
            job = (
                deserialize_export_job(persisted)
                if persisted is not None
                else self._jobs.get(job_id)
            )
            if job is None:
                return None
            self._jobs[job_id] = job
            expires_at = datetime.fromisoformat(job.expires_at.replace("Z", "+00:00"))
            if job.status in {"COMPLETED", "FAILED"} and utc_now() > expires_at:
                await self._expire_job(job)
                job = self._jobs.get(job_id) or job
        try:
            # Same live-authority contract as download/execute: HTTP actor must
            # still be the requester, and the durable registry + authority must
            # still resolve the principal (revoke/downgrade fail closed).
            require_current_export_access(
                actor=actor,
                requester_id=job.requested_by,
                tenant_id=job.tenant_id,
                requested_owner_units=job.requested_owner_units,
                environment=self._environment,
            )
            await self._resolve_worker_actor(job)
        except ExportAuthorizationError:
            return None
        return job

    async def _expire_job(self, job: ExportJob) -> None:
        if job.content_ref:
            await self._content_store.delete(content_ref=job.content_ref)
        previous = job.status
        job.status = "EXPIRED"
        job.result = None
        job.content_ref = None
        job.content_type = None
        job.download_content = None
        job.download_bytes = None
        await self._persist(job)
        try:
            await self._audit(
                ActorContext(
                    user_id=job.requested_by,
                    display_name=job.requested_by,
                    role=job.requested_role,  # type: ignore[arg-type]
                    owner_unit_ids=job.requested_owner_units,
                    tenant_id=job.tenant_id,
                ),
                "export.expire",
                job.job_id,
                after={"previousStatus": previous},
            )
        except AuditWriteError:
            pass

    async def purge_expired_jobs(self) -> int:
        expired_payloads = await self._job_store.list_expired(utc_now())
        removed = 0
        async with self._lock:
            for payload in expired_payloads:
                job = deserialize_export_job(payload)
                await self._expire_job(job)
                self._jobs[job.job_id] = job
                removed += 1
        await self.purge_orphan_artifacts()
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
        job = await self.get_job(job_id, actor=actor)
        if job is None:
            raise ExportAuthorizationError("Export download denied.")
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
