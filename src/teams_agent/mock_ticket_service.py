"""Mock Ticket REST API for local and Cloud Run acceptance testing.

Local mode stores tickets in memory. Cloud Run uses Firestore so tickets
survive instance recycling. The mutable API is protected by an application
Bearer token when ``MOCK_TICKET_TOKEN`` is configured.
"""

from __future__ import annotations

import asyncio
import hmac
import os
from datetime import UTC, datetime
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict


class TicketDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requesterId: str
    requesterName: str
    requesterEmail: str
    title: str
    description: str
    ticketItemId: str
    priority: str = "NORMAL"


app = FastAPI(title="Mock Ticket Service", docs_url=None, redoc_url=None)
_tickets: dict[str, dict[str, str]] = {}
_firestore_client = None


def _store_mode() -> str:
    return os.environ.get("MOCK_TICKET_STORE_MODE", "MEMORY").strip().upper()


def _collection_name() -> str:
    return os.environ.get("MOCK_TICKET_COLLECTION", "mock_tickets").strip()


def _public_base_url(request: Request) -> str:
    configured = os.environ.get("MOCK_TICKET_PUBLIC_BASE_URL", "").strip()
    return (configured or str(request.base_url)).rstrip("/")


def _client():
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore

        _firestore_client = firestore.Client()
    return _firestore_client


def _require_authorization(authorization: str | None) -> None:
    expected = os.environ.get("MOCK_TICKET_TOKEN", "")
    if not expected:
        return
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _save(ticket: dict[str, str]) -> None:
    if _store_mode() == "FIRESTORE":
        await asyncio.to_thread(
            _client().collection(_collection_name()).document(ticket["id"]).set,
            ticket,
        )
    else:
        _tickets[ticket["id"]] = ticket


async def _find(ticket_id: str) -> dict[str, str] | None:
    if _store_mode() == "FIRESTORE":
        snapshot = await asyncio.to_thread(
            _client().collection(_collection_name()).document(ticket_id).get
        )
        return snapshot.to_dict() if snapshot.exists else None
    return _tickets.get(ticket_id)


async def _list_for(requester_id: str) -> list[dict[str, str]]:
    if _store_mode() == "FIRESTORE":
        query = _client().collection(_collection_name()).where(
            filter=_firestore_field_filter("requesterId", "==", requester_id)
        )
        snapshots = await asyncio.to_thread(lambda: list(query.stream()))
        return [snapshot.to_dict() for snapshot in snapshots]
    return [
        ticket
        for ticket in _tickets.values()
        if ticket["requesterId"] == requester_id
    ]


def _firestore_field_filter(field: str, operator: str, value: str):
    from google.cloud.firestore_v1.base_query import FieldFilter

    return FieldFilter(field, operator, value)


@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok", "store": _store_mode()}


@app.get("/ticket-items")
async def ticket_items(
    authorization: str | None = Header(default=None),
) -> list[dict[str, str]]:
    _require_authorization(authorization)
    return [
        {"id": "GENERAL_IT", "name": "一般資訊問題"},
        {"id": "ACCESS", "name": "帳號與權限"},
        {"id": "NETWORK", "name": "網路與 VPN"},
    ]


@app.post("/tickets", status_code=201)
async def create_ticket(
    draft: TicketDraft,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    _require_authorization(authorization)
    ticket_id = f"MOCK-{uuid4().hex[:12].upper()}"
    ticket = {
        "id": ticket_id,
        "title": draft.title,
        "status": "OPEN",
        "createdAt": datetime.now(UTC).isoformat(),
        "url": f"{_public_base_url(request)}/tickets/{ticket_id}",
        "requesterId": draft.requesterId,
    }
    await _save(ticket)
    return ticket


@app.get("/tickets")
async def list_tickets(
    requesterId: str,
    authorization: str | None = Header(default=None),
) -> list[dict[str, str]]:
    _require_authorization(authorization)
    return await _list_for(requesterId)


@app.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    requesterId: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    # A ticket link may be opened directly by the tester. Auth remains
    # mandatory for requester-scoped API reads used by the Agent.
    if requesterId is not None:
        _require_authorization(authorization)
    ticket = await _find(ticket_id)
    if ticket is None or (
        requesterId is not None and ticket["requesterId"] != requesterId
    ):
        raise HTTPException(status_code=404, detail="Ticket not found")
    if requesterId is None:
        return {key: value for key, value in ticket.items() if key != "requesterId"}
    return ticket


def main() -> None:
    port = int(os.environ.get("PORT", os.environ.get("MOCK_TICKET_PORT", "8090")))
    host = "0.0.0.0" if os.environ.get("K_SERVICE") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
