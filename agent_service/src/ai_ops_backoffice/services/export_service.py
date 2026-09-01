from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine, Literal

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import AuditStore, build_audit_event
from agent_service.operations.contracts import utc_now
from agent_service.operations.settings import OpsSettings

ExportJobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "EXPIRED"]


@dataclass
class ExportJob:
    job_id: str
    export_type: str
    status: ExportJobStatus
    reason: str
    requested_by: str
    requested_role: str
    days: int
    created_at: str
    expires_at: str
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class ExportJobService:
    def __init__(
        self,
        *,
        audit_store: AuditStore,
        store_path: Path,
        environment: str,
    ) -> None:
        self._audit_store = audit_store
        self._store_path = store_path
        self._environment = environment
        self._jobs: dict[str, ExportJob] = {}
        self._lock = asyncio.Lock()
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._jobs_file = self._store_path / "export_jobs.json"
        self._load()

    def _load(self) -> None:
        if not self._jobs_file.is_file():
            return
        payload = json.loads(self._jobs_file.read_text(encoding="utf-8"))
        for item in payload:
            job = ExportJob(**item)
            self._jobs[job.job_id] = job

    def _persist(self) -> None:
        self._jobs_file.write_text(
            json.dumps([job.__dict__ for job in self._jobs.values()], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def create_job(
        self,
        *,
        actor: ActorContext,
        export_type: str,
        reason: str,
        days: int,
        runner: Callable[[], Coroutine[Any, Any, dict[str, Any]]],
    ) -> ExportJob:
        job_id = str(uuid.uuid4())
        now = utc_now()
        job = ExportJob(
            job_id=job_id,
            export_type=export_type,
            status="QUEUED",
            reason=reason,
            requested_by=actor.user_id,
            requested_role=actor.role,
            days=days,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=24)).isoformat(),
        )
        async with self._lock:
            self._jobs[job_id] = job
            self._persist()
        await self._audit(actor, "export.create", job_id, after={"exportType": export_type, "days": days})
        asyncio.create_task(self._run_job(job_id, runner))
        return job

    async def _run_job(
        self,
        job_id: str,
        runner: Callable[[], Coroutine[Any, Any, dict[str, Any]]],
    ) -> None:
        async with self._lock:
            job = self._jobs[job_id]
            job.status = "RUNNING"
            self._persist()
        try:
            result = await runner()
            async with self._lock:
                job = self._jobs[job_id]
                job.status = "COMPLETED"
                job.result = result
                job.completed_at = utc_now().isoformat()
                self._persist()
        except Exception as exc:  # noqa: BLE001
            async with self._lock:
                job = self._jobs[job_id]
                job.status = "FAILED"
                job.error = str(exc)
                job.completed_at = utc_now().isoformat()
                self._persist()

    async def get_job(self, job_id: str, *, actor: ActorContext) -> ExportJob | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            expires_at = job.expires_at
            if job.status == "COMPLETED" and utc_now().isoformat() > expires_at:
                job.status = "EXPIRED"
                self._persist()
            if job.requested_by != actor.user_id and actor.role not in {"SYSTEM_ADMIN", "AUDITOR"}:
                return None
            return job

    async def record_download(self, job_id: str, *, actor: ActorContext) -> None:
        await self._audit(actor, "export.download", job_id)

    async def _audit(
        self,
        actor: ActorContext,
        action: str,
        job_id: str,
        *,
        after: dict[str, object] | None = None,
    ) -> None:
        await self._audit_store.append(
            build_audit_event(
                actor_id=actor.user_id,
                actor_role=actor.role,
                action=action,
                target_type="export_job",
                target_id=job_id,
                after=after,
                environment=self._environment,
            )
        )
