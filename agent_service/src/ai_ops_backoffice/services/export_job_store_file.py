"""File-backed durable export job metadata store with process-safe claims."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .export_job_lease import apply_claim, clear_lease_fields, lease_expired, owns_running_lease


class FileExportJobStore:
    """Durable metadata store with process-safe atomic claim via flock.

    The exclusive lock is held on a dedicated ``export_jobs.lock`` file so
    ``os.replace`` of the JSON payload cannot drop the flock inode/handle that
    other processes wait on.
    """

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._path = root / "export_jobs.json"
        self._lock_path = root / "export_jobs.lock"
        self._lock = threading.RLock()

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Hold the process-safe exclusive lock for a critical section."""
        self._lock.acquire()
        handle = None
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            # Dedicated lock file — never replaced by JSON writes.
            handle = self._lock_path.open("a+", encoding="utf-8")
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                # Windows / unsupported FS: threading lock still serializes in-process.
                pass
            if not self._path.exists():
                self._path.write_text("[]", encoding="utf-8")
            yield
        finally:
            try:
                if handle is not None:
                    try:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    except (ImportError, OSError):
                        pass
                    handle.close()
            finally:
                self._lock.release()

    def _read_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return {str(item["job_id"]): item for item in payload}
        return {str(key): value for key, value in payload.items()}

    def _write_unlocked(self, jobs: dict[str, dict[str, Any]]) -> None:
        temporary = self._path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(list(jobs.values()), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        with self._exclusive():
            return self._read_unlocked().get(job_id)

    async def put(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._exclusive():
            jobs = self._read_unlocked()
            jobs[job_id] = payload
            self._write_unlocked(jobs)

    async def delete(self, job_id: str) -> None:
        with self._exclusive():
            jobs = self._read_unlocked()
            jobs.pop(job_id, None)
            self._write_unlocked(jobs)

    async def list_expired(self, before: datetime) -> list[dict[str, Any]]:
        with self._exclusive():
            return [
                payload
                for payload in self._read_unlocked().values()
                if payload.get("status") in {"COMPLETED", "FAILED"}
                and isinstance(payload.get("expires_at"), str)
                and datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")) <= before
            ]

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]:
        with self._exclusive():
            return [
                payload
                for payload in self._read_unlocked().values()
                if payload.get("status") in statuses
            ]

    async def list_all_content_refs(self) -> set[str]:
        with self._exclusive():
            refs: set[str] = set()
            for payload in self._read_unlocked().values():
                ref = payload.get("content_ref")
                if isinstance(ref, str) and ref:
                    refs.add(ref)
            return refs

    async def find_by_idempotency_scope(
        self,
        *,
        key: str,
        tenant_id: str,
        requester_id: str,
    ) -> dict[str, Any] | None:
        if not key:
            return None
        with self._exclusive():
            for payload in self._read_unlocked().values():
                if payload.get("idempotency_key") != key:
                    continue
                if payload.get("tenant_id") != tenant_id:
                    continue
                if payload.get("requested_by") != requester_id:
                    continue
                if payload.get("status") in {"FAILED", "EXPIRED"}:
                    continue
                return payload
        return None

    async def claim_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> dict[str, Any] | None:
        with self._exclusive():
            jobs = self._read_unlocked()
            current = jobs.get(job_id)
            if current is None:
                return None
            status = current.get("status")
            if status == "QUEUED":
                claimed = apply_claim(
                    current, worker_id=worker_id, lease_seconds=lease_seconds, now=now
                )
            elif status == "RUNNING":
                # Never steal a still-valid lease — including the caller's own —
                # so recovery scanners cannot double-dispatch in-flight work.
                if not lease_expired(current, now):
                    return None
                claimed = apply_claim(
                    current, worker_id=worker_id, lease_seconds=lease_seconds, now=now
                )
            else:
                return None
            jobs[job_id] = claimed
            self._write_unlocked(jobs)
            return claimed

    async def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
        now: datetime,
    ) -> bool:
        with self._exclusive():
            jobs = self._read_unlocked()
            current = jobs.get(job_id)
            if current is None:
                return False
            if not owns_running_lease(current, worker_id=worker_id, lease_token=lease_token):
                return False
            current = dict(current)
            current["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
            jobs[job_id] = current
            self._write_unlocked(jobs)
            return True

    async def complete_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool:
        with self._exclusive():
            jobs = self._read_unlocked()
            current = jobs.get(job_id)
            if current is None:
                return False
            if not owns_running_lease(current, worker_id=worker_id, lease_token=lease_token):
                return False
            jobs[job_id] = clear_lease_fields(payload)
            self._write_unlocked(jobs)
            return True

    async def requeue_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool:
        with self._exclusive():
            jobs = self._read_unlocked()
            current = jobs.get(job_id)
            if current is None:
                return False
            if not owns_running_lease(current, worker_id=worker_id, lease_token=lease_token):
                return False
            next_payload = clear_lease_fields(payload)
            next_payload["status"] = "QUEUED"
            jobs[job_id] = next_payload
            self._write_unlocked(jobs)
            return True
