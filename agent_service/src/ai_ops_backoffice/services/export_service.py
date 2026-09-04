from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import AuditStore, build_audit_event
from agent_service.operations.audit_errors import AuditWriteError
from agent_service.operations.contracts import utc_now

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
from .export_format import flatten_for_csv, flatten_for_xlsx
from .export_job_store import ExportJobStore, FileExportJobStore

ExportJobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "EXPIRED"]
LEASE_SECONDS = 120
RECOVERY_SCAN_SECONDS = 30


class ExportExecutionBackend(Protocol):
    """Rebuild export work from persisted job parameters with a fresh actor."""

    async def execute(self, *, actor: ActorContext, job: ExportJob) -> dict[str, Any]: ...


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
    request_params: dict[str, Any] = field(default_factory=dict)
    request_fingerprint: str | None = None
    idempotency_key: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    lease_token: str | None = None
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    download_content: str | None = None
    download_bytes: bytes | None = None
    content_ref: str | None = None
    content_type: str | None = None
    error: str | None = None


def export_request_fingerprint(
    *,
    export_type: str,
    export_format: str,
    days: int,
    reason: str,
    request_params: dict[str, Any] | None,
) -> str:
    payload = {
        "export_type": export_type,
        "export_format": export_format,
        "days": days,
        "reason": reason,
        "request_params": request_params or {},
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
        export_authority: ExportAuthoritySource | None = None,
        require_export_authority: bool | None = None,
        execution_backend: ExportExecutionBackend | None = None,
        worker_id: str | None = None,
        run_inline: bool = False,
        lease_seconds: int = LEASE_SECONDS,
        recovery_scan_seconds: int = RECOVERY_SCAN_SECONDS,
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
        lab_environment = environment.lower() in {"dev", "test", "poc", "lab"}
        if require_export_authority is None:
            require_export_authority = not lab_environment
        if authorization_resolver is not None:
            self._authorization_resolver = authorization_resolver
        elif require_export_authority and export_authority is None:
            # Production must not silently accept file-registry-only revoke checks.
            self._authorization_resolver = UnavailableExportAuthorizationResolver()
        else:
            self._authorization_resolver = FileBackedExportAuthorizationResolver(
                self._store_path / "export_auth_registry.json",
                authority=export_authority,
            )
        self._execution_backend = execution_backend
        self._legacy_runners: dict[str, Callable[[], Coroutine[Any, Any, dict[str, Any]]]] = {}
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._run_inline = run_inline
        self._lease_seconds = lease_seconds
        self._recovery_scan_seconds = recovery_scan_seconds
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._pending_content_refs: set[str] = set()

    def configure_authorization_resolver(
        self,
        resolver: ExportAuthorizationResolver,
    ) -> None:
        self._authorization_resolver = resolver

    def configure_execution_backend(self, backend: ExportExecutionBackend) -> None:
        self._execution_backend = backend

    async def _persist(self, job: ExportJob) -> None:
        await self._job_store.put(job.job_id, self._serialize_job(job))

    def _serialize_job(self, job: ExportJob) -> dict[str, Any]:
        payload = job.__dict__.copy()
        download_bytes = payload.pop("download_bytes", None)
        if download_bytes is not None:
            payload["download_bytes_b64"] = base64.b64encode(download_bytes).decode("ascii")
        payload["requested_owner_units"] = list(job.requested_owner_units)
        payload["request_params"] = dict(job.request_params or {})
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
            "request_params": {},
            "request_fingerprint": None,
            "idempotency_key": None,
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_owner": None,
            "lease_expires_at": None,
            "lease_token": None,
            "error": None,
            "result": None,
            "completed_at": None,
        }
        merged = {**defaults, **item}
        for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
            if isinstance(merged.get(key), datetime):
                merged[key] = merged[key].isoformat()
        encoded = merged.pop("download_bytes_b64", None)
        if encoded:
            merged["download_bytes"] = base64.b64decode(encoded)
        units = merged.get("requested_owner_units") or ()
        merged["requested_owner_units"] = tuple(units)
        merged["request_params"] = dict(merged.get("request_params") or {})
        known = {item.name for item in fields(ExportJob)}
        return ExportJob(**{key: value for key, value in merged.items() if key in known})

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
            existing_payload = await self._job_store.find_by_idempotency_scope(
                key=idempotency_key,
                tenant_id=tenant_id,
                requester_id=actor.user_id,
            )
            if existing_payload is not None:
                existing = self._deserialize_job(existing_payload)
                if existing.request_fingerprint and existing.request_fingerprint != fingerprint:
                    raise ExportIdempotencyConflictError(
                        "Idempotency key was reused with different export parameters."
                    )
                self._jobs[existing.job_id] = existing
                return existing

        job_id = str(uuid.uuid4())
        now = utc_now()
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
            request_params=dict(request_params or {}),
            request_fingerprint=fingerprint,
            idempotency_key=idempotency_key,
        )
        async with self._lock:
            self._jobs[job_id] = job
            if runner is not None:
                self._legacy_runners[job_id] = runner
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
                    "idempotencyKey": idempotency_key,
                    "requestFingerprint": fingerprint,
                    **(request_metadata or {}),
                },
            )
        except AuditWriteError:
            async with self._lock:
                self._jobs.pop(job_id, None)
                self._legacy_runners.pop(job_id, None)
                await self._job_store.delete(job_id)
            raise
        self._schedule(self._run_job(job_id))
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
            job = self._deserialize_job(payload)
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
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._recovery_scan_seconds
                )
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

    async def _run_job(self, job_id: str) -> None:
        claimed_payload = await self._job_store.claim_job(
            job_id,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
            now=utc_now(),
        )
        if claimed_payload is None:
            return
        job = self._deserialize_job(claimed_payload)
        lease_token = job.lease_token or ""
        self._jobs[job_id] = job
        renew_task: asyncio.Task[None] | None = None
        stop_renew = asyncio.Event()
        pending_content_ref: str | None = None

        async def _renew_loop() -> None:
            while not stop_renew.is_set():
                try:
                    await asyncio.wait_for(
                        stop_renew.wait(), timeout=max(5, self._lease_seconds // 3)
                    )
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

        try:
            renew_task = asyncio.create_task(_renew_loop())
            actor = await self._resolve_worker_actor(job)
            result = await self._execute(actor=actor, job=job)
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
            # Track pending artifact before audit/persist so failure paths can
            # delete it even when job.content_ref was never committed.
            content_ref = await self._content_store.put(
                job_id=job_id,
                content=content,
                content_type=content_type,
                attempt=job.attempt_count,
                lease_token=lease_token,
            )
            pending_content_ref = content_ref
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
            except Exception:
                await self._content_store.delete(content_ref=content_ref)
                self._pending_content_refs.discard(content_ref)
                pending_content_ref = None
                raise
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
                payload=self._serialize_job(job),
            )
            if not committed:
                # Lost lease mid-flight — another worker owns the job; drop orphan content.
                await self._content_store.delete(content_ref=content_ref)
                self._pending_content_refs.discard(content_ref)
                pending_content_ref = None
                return
            self._pending_content_refs.discard(content_ref)
            pending_content_ref = None
            self._jobs[job_id] = job
        except Exception as exc:  # noqa: BLE001
            current = self._jobs.get(job_id) or job
            if pending_content_ref:
                await self._content_store.delete(content_ref=pending_content_ref)
                self._pending_content_refs.discard(pending_content_ref)
            if current.content_ref and current.content_ref != pending_content_ref:
                await self._content_store.delete(content_ref=current.content_ref)
            retryable = (
                current.attempt_count < current.max_attempts
                and isinstance(exc, (TimeoutError, ConnectionError, OSError))
            )
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
                    payload=self._serialize_job(current),
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
                payload=self._serialize_job(current),
            )
            if committed:
                self._jobs[job_id] = current
        finally:
            stop_renew.set()
            if renew_task is not None:
                renew_task.cancel()
                with suppress(asyncio.CancelledError):
                    await renew_task

    async def get_job(self, job_id: str, *, actor: ActorContext) -> ExportJob | None:
        async with self._lock:
            persisted = await self._job_store.get(job_id)
            job = self._deserialize_job(persisted) if persisted is not None else self._jobs.get(job_id)
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
                job = self._deserialize_job(payload)
                await self._expire_job(job)
                self._jobs[job.job_id] = job
                removed += 1
        await self.purge_orphan_artifacts()
        return removed

    async def purge_orphan_artifacts(self, *, min_age_seconds: int | None = None) -> int:
        """Delete attempt artifacts that no live job still references.

        Artifacts younger than ``min_age_seconds`` are kept so an in-flight
        worker that has uploaded but not yet committed ``content_ref`` is not
        raced by the sweeper. Cross-process pending uploads are covered by age;
        same-process pending refs are tracked in ``_pending_content_refs``.

        Fail closed: incomplete reference scans or unknown artifact age retain
        the object rather than treating "not in a capped page" as orphaned.
        """
        list_refs = getattr(self._content_store, "list_refs", None)
        if not callable(list_refs):
            return 0
        min_age = (
            min_age_seconds
            if min_age_seconds is not None
            else max(300, self._lease_seconds * 3)
        )
        referenced = await self._collect_referenced_content_refs()
        if referenced is None:
            return 0
        removed = 0
        now_ts = utc_now().timestamp()
        for content_ref in await list_refs():
            if content_ref in referenced or content_ref in self._pending_content_refs:
                continue
            if not await self._artifact_older_than(
                content_ref, now_ts=now_ts, min_age_seconds=min_age
            ):
                continue
            # Re-check references immediately before delete (lease/commit race).
            fresh = await self._collect_referenced_content_refs()
            if fresh is None or content_ref in fresh or content_ref in self._pending_content_refs:
                continue
            await self._content_store.delete(content_ref=content_ref)
            removed += 1
        return removed

    async def _collect_referenced_content_refs(self) -> set[str] | None:
        """Return complete durable refs, or ``None`` when the scan is incomplete."""
        list_all = getattr(self._job_store, "list_all_content_refs", None)
        referenced: set[str] = set(self._pending_content_refs)
        if callable(list_all):
            try:
                referenced.update(await list_all())
            except Exception:  # noqa: BLE001
                return None
        else:
            # Legacy stores without a complete scanner must not drive deletes.
            return None
        async with self._lock:
            for job in self._jobs.values():
                if job.content_ref:
                    referenced.add(job.content_ref)
        return referenced

    async def _artifact_older_than(
        self,
        content_ref: str,
        *,
        now_ts: float,
        min_age_seconds: int,
    ) -> bool:
        created_at = None
        created_at_fn = getattr(self._content_store, "created_at_epoch", None)
        if callable(created_at_fn):
            try:
                created_at = await created_at_fn(content_ref)
            except Exception:  # noqa: BLE001
                created_at = None
        if created_at is None:
            # Unknown age (remote backend without metadata) — retain.
            return False
        return (now_ts - float(created_at)) >= min_age_seconds

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
