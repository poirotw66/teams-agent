"""Export job metadata store protocol and backend re-exports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from .export_job_store_file import FileExportJobStore
from .export_job_store_firestore import FirestoreExportJobStore

__all__ = [
    "ExportJobStore",
    "FileExportJobStore",
    "FirestoreExportJobStore",
]


class ExportJobStore(Protocol):
    async def get(self, job_id: str) -> dict[str, Any] | None: ...

    async def put(self, job_id: str, payload: dict[str, Any]) -> None: ...

    async def delete(self, job_id: str) -> None: ...

    async def list_expired(self, before: datetime) -> list[dict[str, Any]]: ...

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]: ...

    async def list_all_content_refs(self) -> set[str]:
        """Return every durable ``content_ref``. Must be complete (no page caps)."""
        ...

    async def find_by_idempotency_scope(
        self,
        *,
        key: str,
        tenant_id: str,
        requester_id: str,
    ) -> dict[str, Any] | None: ...

    async def claim_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> dict[str, Any] | None: ...

    async def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
        now: datetime,
    ) -> bool: ...

    async def complete_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool: ...

    async def requeue_if_owner(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> bool: ...
