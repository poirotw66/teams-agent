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
    -> ``200`` with BU's ``Code``/``Msg``/``Data.items`` envelope containing
       a recursive category tree. Only leaf nodes are exposed to the
       workflow as selectable ``TicketItem`` objects. A legacy flat JSON
       array remains accepted during migration.
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

from typing import Protocol

from .contracts import Ticket, TicketDraft, TicketItem
from .settings import RagSettings
from .ticket_catalog import (
    AgenticTicketItemSelector,
    TicketItemSelection,
    TicketItemSelectionDecision,
    handoff_ticket_item_fallback,
    parse_ticket_items_payload,
)
from .ticket_errors import (
    TicketCatalogError,
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
    UntrustedRequesterError,
)
from .ticket_http import HttpTicketService

__all__ = [
    "AgenticTicketItemSelector",
    "DisabledTicketService",
    "HttpTicketService",
    "TicketCatalogError",
    "TicketItemSelection",
    "TicketItemSelectionDecision",
    "TicketService",
    "TicketServiceDisabledError",
    "TicketServiceError",
    "TicketServiceTimeout",
    "UntrustedRequesterError",
    "build_ticket_service",
    "handoff_ticket_item_fallback",
    "parse_ticket_items_payload",
]


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
        self,
        draft: TicketDraft,
        *,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
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
        self,
        draft: TicketDraft,
        *,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
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
