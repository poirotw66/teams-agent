"""HTTP-backed Ticket Service adapter (spec §11.2, ``HTTP`` mode)."""

from __future__ import annotations

import logging

import httpx

from .contracts import Ticket, TicketDraft, TicketItem
from .ticket_catalog import parse_ticket_items_payload
from .ticket_errors import (
    TicketServiceError,
    TicketServiceTimeout,
    UntrustedRequesterError,
)

logger = logging.getLogger(__name__)


def _ticket_from_payload(payload: dict) -> tuple[Ticket, str | None]:
    """Split a raw backend JSON object into a strict ``Ticket`` plus its
    ``requesterId`` (kept out of the ``Ticket`` model itself, which is a
    ``StrictModel`` with ``extra="forbid"`` and has no requester field).
    """
    requester_id = payload.get("requesterId")
    known_fields = set(Ticket.model_fields)
    fields = {key: value for key, value in payload.items() if key in known_fields}
    return Ticket(**fields), requester_id


class HttpTicketService:
    """Ticket Service backed by an HTTP REST API (spec §11.2, ``HTTP`` mode).

    See the ``ticket`` module docstring for the exact endpoint contract. This
    adapter is deliberately generic: it has no knowledge of whether it is
    talking to a mock or a production ticket system (spec §11.2).
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_seconds
        # Caller may inject a client (e.g. wired to httpx.MockTransport in
        # tests) so no real network access ever happens in the test suite.
        self._client = client or httpx.AsyncClient(base_url=self._base_url)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(
        self, correlation_id: str | None, idempotency_key: str | None = None
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        # SECURITY (spec §15.2/§17): never log this header or the token
        # itself anywhere — it is only ever placed on the outgoing request.
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if correlation_id:
            headers["X-Correlation-Id"] = correlation_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        headers = self._headers(correlation_id, idempotency_key)
        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            # Do not include headers/token in the log or exception message.
            logger.warning("Ticket service request timed out: %s %s", method, path)
            raise TicketServiceTimeout(
                f"Ticket service timed out calling {method} {path}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "Ticket service request failed: %s %s (%s)", method, path, exc
            )
            raise TicketServiceError(
                f"Ticket service request failed calling {method} {path}"
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "Ticket service returned error status: %s %s -> %s",
                method,
                path,
                response.status_code,
            )
            raise TicketServiceError(
                f"Ticket service returned {response.status_code} for {method} {path}",
                status_code=response.status_code,
            )
        return response

    async def get_ticket_items(
        self, *, correlation_id: str | None = None
    ) -> list[TicketItem]:
        response = await self._request(
            "GET", "/ticket-items", correlation_id=correlation_id
        )
        return parse_ticket_items_payload(response.json())

    async def create_ticket(
        self,
        draft: TicketDraft,
        *,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Ticket:
        # Spec §11.4: reject an incomplete/untrusted requester identity
        # BEFORE making any HTTP call.
        if (
            not draft.requesterId.strip()
            or not draft.requesterName.strip()
            or not draft.requesterEmail.strip()
        ):
            raise UntrustedRequesterError(
                "Cannot create a ticket without a trusted requesterId/name/email."
            )

        response = await self._request(
            "POST",
            "/tickets",
            json=draft.model_dump(),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        ticket, _requester_id = _ticket_from_payload(response.json())
        return ticket

    async def list_tickets_by_requester(
        self, requester_id: str, *, correlation_id: str | None = None
    ) -> list[Ticket]:
        response = await self._request(
            "GET",
            "/tickets",
            params={"requesterId": requester_id},
            correlation_id=correlation_id,
        )
        tickets: list[Ticket] = []
        for raw in response.json():
            ticket, owner = _ticket_from_payload(raw)
            # Defense in depth (spec §17): even though we asked the backend
            # to scope by requesterId, don't trust it blindly.
            if owner is not None and owner != requester_id:
                continue
            tickets.append(ticket)
        return tickets

    async def get_ticket(
        self, ticket_id: str, requester_id: str, *, correlation_id: str | None = None
    ) -> Ticket | None:
        response = await self._request(
            "GET",
            f"/tickets/{ticket_id}",
            params={"requesterId": requester_id},
            correlation_id=correlation_id,
        )
        ticket, owner = _ticket_from_payload(response.json())
        # Defense in depth (spec §17): refuse to return another user's
        # ticket even if a permissive backend returned one.
        if owner is not None and owner != requester_id:
            return None
        return ticket
