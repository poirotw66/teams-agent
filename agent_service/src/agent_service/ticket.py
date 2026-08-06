"""Ticket Service adapter (spec §3.2, §11).

Per spec §3.2 the LangGraph workflow must never depend on a concrete ticket
backend — it only sees the ``TicketService`` Protocol defined here. Per
spec §11.2, the agent must not be able to tell whether ``HTTP`` mode is
backed by a mock or the real ticket system: the adapter is a thin, generic
HTTP client with no backend-specific branching.

Modes (spec §11.2)
-------------------
- ``DISABLED``: ticket creation/lookup is turned off entirely. All calls
  raise :class:`TicketServiceDisabledError` so the workflow can surface a
  clear "工單功能未啟用" message instead of crashing.
- ``HTTP``: calls a REST backend at ``settings.ticket_service_base_url``.

HTTP endpoint contract
-----------------------
The ``HttpTicketService`` assumes the following REST surface. Any real or
mock ticket backend wired up in HTTP mode must implement this contract:

- ``GET  {base_url}/ticket-items``
    -> ``200`` with a JSON array of ``{"id": str, "name": str}`` objects.
- ``POST {base_url}/tickets``
    body: the ``TicketDraft`` fields as JSON.
    -> ``201``/``200`` with a JSON object containing at least
       ``{"id": str, "title": str, "status": str}`` (``createdAt``/``url``
       optional), plus a ``requesterId`` field used for a defense-in-depth
       ownership check on subsequent reads.
- ``GET  {base_url}/tickets?requesterId={requesterId}``
    -> ``200`` with a JSON array of ticket objects (same shape as above),
       already scoped to the requester by the backend.
- ``GET  {base_url}/tickets/{ticket_id}?requesterId={requesterId}``
    -> ``200`` with a single ticket object, or ``404`` if not found.

Requests carry ``Authorization: Bearer {ticket_service_token}`` when a
token is configured, and (when supplied by the caller) an
``X-Correlation-Id`` header per spec §15.1.

Scope note (spec §11.5, §19)
-----------------------------
This module intentionally does NOT implement: an Issue/ticket repository,
ticket lifecycle/state machine, 催辦 (nudging) or reminder platform, ticket
cancellation, or supplementary-info flows. It is a thin adapter only.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from .contracts import Ticket, TicketDraft, TicketItem
from .settings import RagSettings

logger = logging.getLogger(__name__)


# --- Exceptions -------------------------------------------------------


class TicketServiceError(Exception):
    """Base error for ticket-service failures.

    Carries the HTTP status code when one is available (spec §18.5 requires
    both timeout and generic error cases to be distinguishable/testable).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TicketServiceTimeout(TicketServiceError):
    """Raised when a call to the HTTP ticket backend times out."""


class TicketServiceDisabledError(TicketServiceError):
    """Raised by :class:`DisabledTicketService` for every operation."""

    def __init__(self, message: str = "工單功能未啟用") -> None:
        super().__init__(message, status_code=None)


class UntrustedRequesterError(Exception):
    """Raised when a ticket draft's requester identity is incomplete.

    Spec §11.4: requesterId/name/email must come from trusted Teams/Entra
    context. If any is missing or blank, the ticket must NOT be created —
    this is raised before any HTTP call is attempted.
    """


# --- Protocol (spec §11.1) --------------------------------------------


class TicketService(Protocol):
    """Interface the LangGraph workflow depends on (spec §3.2, §11.1).

    The workflow must only ever hold a reference to this Protocol, never to
    a concrete adapter, so it cannot distinguish DISABLED/HTTP or mock/real
    backends (spec §11.2).
    """

    async def get_ticket_items(
        self, *, correlation_id: str | None = None
    ) -> list[TicketItem]:
        """Return the catalog of ticket item types available to select from."""
        ...

    async def create_ticket(
        self, draft: TicketDraft, *, correlation_id: str | None = None
    ) -> Ticket:
        """Create at most one ticket from an already-confirmed draft.

        The caller is responsible for spec §11.3 (explicit confirmation)
        and §11.5 (at most one ticket per turn) — this call performs a
        single creation and nothing more.
        """
        ...

    async def list_tickets_by_requester(
        self, requester_id: str, *, correlation_id: str | None = None
    ) -> list[Ticket]:
        """Return tickets belonging to ``requester_id`` only (spec §17)."""
        ...

    async def get_ticket(
        self, ticket_id: str, requester_id: str, *, correlation_id: str | None = None
    ) -> Ticket | None:
        """Return a single ticket iff it belongs to ``requester_id``.

        Returns ``None`` (not-found) rather than another user's ticket if
        there is an ownership mismatch — enforcing "只能看自己的工單" is the
        service's job, not the caller's (spec §11.1, §17).
        """
        ...


# --- DISABLED mode -------------------------------------------------------


class DisabledTicketService:
    """Ticket Service used when ``TICKET_SERVICE_MODE=DISABLED``.

    Every operation raises :class:`TicketServiceDisabledError` so callers
    can catch a single typed exception and surface a clear "工單功能未啟用"
    message instead of crashing or silently no-op'ing.
    """

    async def get_ticket_items(
        self, *, correlation_id: str | None = None
    ) -> list[TicketItem]:
        raise TicketServiceDisabledError()

    async def create_ticket(
        self, draft: TicketDraft, *, correlation_id: str | None = None
    ) -> Ticket:
        raise TicketServiceDisabledError()

    async def list_tickets_by_requester(
        self, requester_id: str, *, correlation_id: str | None = None
    ) -> list[Ticket]:
        raise TicketServiceDisabledError()

    async def get_ticket(
        self, ticket_id: str, requester_id: str, *, correlation_id: str | None = None
    ) -> Ticket | None:
        raise TicketServiceDisabledError()


# --- HTTP mode -------------------------------------------------------


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

    See the module docstring for the exact endpoint contract. This adapter
    is deliberately generic: it has no knowledge of whether it is talking
    to a mock or a production ticket system (spec §11.2).
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

    def _headers(self, correlation_id: str | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        # SECURITY (spec §15.2/§17): never log this header or the token
        # itself anywhere — it is only ever placed on the outgoing request.
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if correlation_id:
            headers["X-Correlation-Id"] = correlation_id
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        correlation_id: str | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        headers = self._headers(correlation_id)
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
            logger.warning("Ticket service request failed: %s %s (%s)", method, path, exc)
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
        return [TicketItem(**item) for item in response.json()]

    async def create_ticket(
        self, draft: TicketDraft, *, correlation_id: str | None = None
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


# --- Factory -------------------------------------------------------


def build_ticket_service(settings: RagSettings) -> TicketService:
    """Build the configured ``TicketService`` per spec §11.2.

    Only ``DISABLED`` and ``HTTP`` are supported. ``settings.validate()``
    already rejects any other value, so this is a closed match.
    """
    if settings.ticket_service_mode == "DISABLED":
        return DisabledTicketService()
    if settings.ticket_service_mode == "HTTP":
        if not settings.ticket_service_base_url:
            raise ValueError(
                "TICKET_SERVICE_BASE_URL is required when TICKET_SERVICE_MODE=HTTP."
            )
        return HttpTicketService(
            settings.ticket_service_base_url,
            token=settings.ticket_service_token,
            timeout_seconds=settings.ticket_service_timeout_seconds,
        )
    raise ValueError(f"Unsupported TICKET_SERVICE_MODE: {settings.ticket_service_mode}")
