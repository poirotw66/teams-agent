"""Persistent request ledger for idempotent ticket creation and safe retries."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from .settings import RagSettings

LedgerStatus = Literal["PROCESSING", "COMPLETED", "FAILED"]


class TicketRequestDedupeRepository(Protocol):
    async def get_ticket_id(self, tenant_id: str | None, request_id: str) -> str | None: ...

    async def put(self, tenant_id: str | None, request_id: str, ticket_id: str) -> None: ...


def _ledger_document_id(tenant_id: str | None, request_id: str) -> str:
    raw = f"{tenant_id or '-'}\0{request_id}".encode()
    return hashlib.sha256(raw).hexdigest()


class InMemoryTicketRequestDedupeRepository:
    """Process-safe in-memory dedupe store for tests and MEMORY mode."""

    def __init__(self) -> None:
        self._records: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def get_ticket_id(self, tenant_id: str | None, request_id: str) -> str | None:
        key = _ledger_document_id(tenant_id, request_id)
        async with self._lock:
            return self._records.get(key)

    async def put(self, tenant_id: str | None, request_id: str, ticket_id: str) -> None:
        key = _ledger_document_id(tenant_id, request_id)
        async with self._lock:
            self._records.setdefault(key, ticket_id)


class FirestoreTicketRequestDedupeRepository:
    """Persistent dedupe ledger keyed by tenantId + requestId."""

    def __init__(
        self,
        client: Any,
        *,
        collection: str,
        retention_days: int,
    ) -> None:
        self._client = client
        self._collection = collection
        self._retention_days = retention_days

    def _document(self, tenant_id: str | None, request_id: str) -> Any:
        doc_id = _ledger_document_id(tenant_id, request_id)
        return self._client.collection(self._collection).document(doc_id)

    async def get_ticket_id(self, tenant_id: str | None, request_id: str) -> str | None:
        snapshot = await self._document(tenant_id, request_id).get()
        if not snapshot.exists:
            return None
        payload = snapshot.to_dict() or {}
        if payload.get("status") != "COMPLETED":
            return None
        ticket_id = payload.get("ticketId")
        return str(ticket_id) if ticket_id else None

    async def put(self, tenant_id: str | None, request_id: str, ticket_id: str) -> None:
        document = self._document(tenant_id, request_id)
        snapshot = await document.get()
        if snapshot.exists and (snapshot.to_dict() or {}).get("ticketId"):
            return
        expires_at = datetime.now(UTC) + timedelta(days=self._retention_days)
        await document.set(
            {
                "tenantId": tenant_id,
                "requestId": request_id,
                "ticketId": ticket_id,
                "status": "COMPLETED",
                "createdAt": datetime.now(UTC),
                "expiresAt": expires_at,
            }
        )


def build_ticket_request_dedupe(
    settings: RagSettings,
    *,
    firestore_client: Any | None = None,
) -> TicketRequestDedupeRepository:
    if settings.ticket_request_dedupe_mode == "MEMORY":
        return InMemoryTicketRequestDedupeRepository()
    if firestore_client is not None:
        client = firestore_client
    else:
        try:
            from google.cloud.firestore import AsyncClient
        except ImportError as exc:  # pragma: no cover - Cloud image installs the extra
            raise RuntimeError(
                "TICKET_REQUEST_DEDUPE_MODE=FIRESTORE requires google-cloud-firestore."
            ) from exc
        kwargs: dict[str, str] = {}
        if settings.ticket_request_dedupe_firestore_project:
            kwargs["project"] = settings.ticket_request_dedupe_firestore_project
        if settings.ticket_request_dedupe_firestore_database:
            kwargs["database"] = settings.ticket_request_dedupe_firestore_database
        client = AsyncClient(**kwargs)
    return FirestoreTicketRequestDedupeRepository(
        client,
        collection=settings.ticket_request_dedupe_collection,
        retention_days=settings.ticket_request_dedupe_retention_days,
    )
