"""Fresh authorization boundary for durable export commands.

The command only stores a requester subject and tenant.  A worker must resolve
that subject again; it must never deserialize an actor captured when HTTP
accepted the request.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from agent_service.operations.access import ActorContext


class ExportAuthorizationError(RuntimeError):
    """The requester is no longer entitled to access or run an export."""


class ExportIdempotencyConflictError(RuntimeError):
    """Same idempotency key was reused with a different request fingerprint."""


class ExportAuthorizationResolver(Protocol):
    async def resolve(self, *, requester_id: str, tenant_id: str) -> ActorContext | None:
        """Return the current trusted principal, or ``None`` when revoked."""


class ExportAuthoritySource(Protocol):
    """Optional live authority (Entra / governance revoke list).

    Durable registry alone is not source-of-truth for suspension/downgrade.
    """

    def revalidate(self, actor: ActorContext) -> ActorContext | None:
        """Return an updated actor, or ``None`` when access must be denied."""


class UnavailableExportAuthorizationResolver:
    """Production-safe default before an Entra/Graph/IAM adapter is wired."""

    async def resolve(self, *, requester_id: str, tenant_id: str) -> ActorContext | None:
        _ = requester_id, tenant_id
        raise ExportAuthorizationError("Export authorization provider is not configured.")


class DevelopmentExportAuthorizationResolver:
    """Explicitly development/test-only in-memory resolver."""

    def __init__(self) -> None:
        self._actors: dict[tuple[str, str], ActorContext] = {}

    def register(self, *, actor: ActorContext, tenant_id: str) -> None:
        self._actors[(actor.user_id, tenant_id)] = actor

    async def resolve(self, *, requester_id: str, tenant_id: str) -> ActorContext | None:
        return self._actors.get((requester_id, tenant_id))


class RoleRevalidatingExportAuthorizationResolver:
    """Bind requester identity at create; rebuild ActorContext on resolve.

    Capability checks use the live ``CAPABILITIES`` matrix for the stored role,
    so a role downgrade in the registry is reflected without trusting a stale
    frozen capability set from the original HTTP request closure.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], tuple[str, str, tuple[str, ...]]] = {}
        self._revoked: set[str] = set()

    def register(self, *, actor: ActorContext, tenant_id: str) -> None:
        self._records[(actor.user_id, tenant_id)] = (
            actor.role,
            actor.display_name,
            tuple(actor.owner_unit_ids),
        )
        self._revoked.discard(actor.user_id)

    def revoke(self, requester_id: str) -> None:
        self._revoked.add(requester_id)

    async def resolve(self, *, requester_id: str, tenant_id: str) -> ActorContext | None:
        if requester_id in self._revoked:
            return None
        record = self._records.get((requester_id, tenant_id))
        if record is None:
            return None
        role, display_name, owner_unit_ids = record
        return ActorContext(
            user_id=requester_id,
            display_name=display_name,
            role=role,  # type: ignore[arg-type]
            owner_unit_ids=owner_unit_ids,
            tenant_id=tenant_id,
        )


class AuthorityAwareExportAuthorizationResolver:
    """Compose durable registry with a live authority revalidation hook."""

    def __init__(
        self,
        durable: ExportAuthorizationResolver,
        *,
        authority: ExportAuthoritySource | None = None,
    ) -> None:
        self._durable = durable
        self._authority = authority

    def register(self, *, actor: ActorContext, tenant_id: str) -> None:
        register = getattr(self._durable, "register", None)
        if callable(register):
            register(actor=actor, tenant_id=tenant_id)

    def revoke(self, requester_id: str) -> None:
        revoke = getattr(self._durable, "revoke", None)
        if callable(revoke):
            revoke(requester_id)

    async def resolve(self, *, requester_id: str, tenant_id: str) -> ActorContext | None:
        actor = await self._durable.resolve(requester_id=requester_id, tenant_id=tenant_id)
        if actor is None:
            return None
        if self._authority is None:
            return actor
        return self._authority.revalidate(actor)


class GovernanceRevocationAuthority:
    """Deny export access when the principal is on the governance revoke list."""

    def __init__(self, load_revoked: Callable[[], set[str] | frozenset[str] | list[str]]) -> None:
        self._load_revoked = load_revoked

    def revalidate(self, actor: ActorContext) -> ActorContext | None:
        revoked = set(self._load_revoked() or ())
        if actor.user_id in revoked:
            return None
        return actor


def tenant_for_actor(actor: ActorContext, *, environment: str) -> str:
    """Read tenant provenance supplied by the security-owned ActorContext.

    Header clients cannot choose an arbitrary cross-tenant value in production
    Entra mode; HEADER lab mode may supply ``X-Backoffice-Tenant-Id`` or the
    default ``local-development`` binding.
    """
    tenant_id = actor.tenant_id
    if isinstance(tenant_id, str) and tenant_id.strip():
        return tenant_id.strip()
    if environment.lower() in {"dev", "test", "poc", "lab"}:
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
