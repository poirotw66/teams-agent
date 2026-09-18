"""Typed failures for the Ticket Service adapter (spec §11, §18.5)."""

from __future__ import annotations


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


class TicketCatalogError(TicketServiceError):
    """Raised when the backend ticket-item catalog is unsuccessful or malformed."""
