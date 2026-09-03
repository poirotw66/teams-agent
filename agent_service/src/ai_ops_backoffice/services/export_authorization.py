"""Fresh authorization boundary for durable export commands.

The command only stores a requester subject and tenant.  A worker must resolve
that subject again; it must never deserialize an actor captured when HTTP
accepted the request.
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from agent_service.operations.access import ActorContext


class ExportAuthorizationError(RuntimeError):
    """The requester is no longer entitled to access or run an export."""


class ExportAuthorizationResolver(Protocol):
    async def resolve(self, *, requester_id: str, tenant_id: str) -> ActorContext | None:
        """Return the current trusted principal, or ``None`` when revoked."""


class UnavailableExportAuthorizationResolver:
    """Production-safe default before an Entra/Graph/IAM adapter is wired."""

    async def resolve(self, *, requester_id: str, tenant_id: str) -> ActorContext | None:
        _ = requester_id, tenant_id
        raise ExportAuthorizationError("Export authorization provider is not configured.")


class DevelopmentExportAuthorizationResolver:
    """Explicitly development/test-only in-memory resolver.

    It is intentionally not selected in a non-development environment.  Its
    purpose is to make local API fixtures exercise fresh resolution rather than
    letting the worker retain a closure over an HTTP actor.
    """

    def __init__(self) -> None:
        self._actors: dict[tuple[str, str], ActorContext] = {}

    def register(self, *, actor: ActorContext, tenant_id: str) -> None:
        self._actors[(actor.user_id, tenant_id)] = actor

    async def resolve(self, *, requester_id: str, tenant_id: str) -> ActorContext | None:
        return self._actors.get((requester_id, tenant_id))


def tenant_for_actor(actor: ActorContext, *, environment: str) -> str:
    """Read tenant provenance supplied by the security-owned ActorContext.

    Header clients cannot choose this value.  A synthetic tenant is permitted
    only for isolated dev/test fixtures until the Entra adapter supplies it.
    """
    tenant_id = getattr(actor, "tenant_id", None)
    if isinstance(tenant_id, str) and tenant_id.strip():
        return tenant_id.strip()
    if environment.lower() in {"dev", "test"}:
        return "local-development"
    raise ExportAuthorizationError("Trusted tenant provenance is required for exports.")


def require_current_export_access(
    *,
    actor: ActorContext,
    requester_id: str,
    tenant_id: str,
    requested_owner_units: tuple[str, ...],
    environment: str,
) -> None:
    """Enforce requester identity, tenant, current capability and current scope."""
    if actor.user_id != requester_id:
        raise ExportAuthorizationError("Export jobs are available only to their requester.")
    if tenant_for_actor(actor, environment=environment) != tenant_id:
        raise ExportAuthorizationError("Export tenant does not match the current principal.")
    # A requester who was downgraded after submitting a job must not recover its
    # artifact merely because they retain the generic read capability.
    if not actor.has_capability("ops.exports.create") or not actor.has_capability("ops.exports.read"):
        raise ExportAuthorizationError("Current export capability is required.")
    if not all(actor.allows_owner_unit(unit) for unit in requested_owner_units):
        raise ExportAuthorizationError("Current data scope no longer covers this export.")
