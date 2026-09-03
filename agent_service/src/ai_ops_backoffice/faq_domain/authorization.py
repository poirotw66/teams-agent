from __future__ import annotations

from typing import Protocol

from agent_service.operations.access import ActorContext

from .errors import FaqAuthorizationError


class FaqAuthorizationPort(Protocol):
    """An authority decision, not a caller-supplied boolean escape hatch."""

    def require(self, *, actor: ActorContext, capability: str, owner_unit_id: str) -> None: ...


class AccessPolicyAuthorization:
    """Adapts Phase 0 capability + owner-unit rules and fails closed by default."""

    def require(self, *, actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        if not actor.has_capability(capability) or not actor.allows_owner_unit(owner_unit_id):
            raise FaqAuthorizationError(
                f"Actor is not authorized for {capability} in owner unit {owner_unit_id}."
            )


class FaqTaxonomyPort(Protocol):
    def require_active(self, issue_type_id: str) -> None: ...


class DenyUnknownTaxonomy:
    """Safe default until the Phase 0 taxonomy adapter is wired by the host service."""

    def require_active(self, issue_type_id: str) -> None:
        raise FaqAuthorizationError(f"No active taxonomy authority for {issue_type_id}.")


class FaqSelfApprovalExceptionPort(Protocol):
    def require(self, *, actor: ActorContext, owner_unit_id: str, reason: str) -> None: ...


class DenySelfApprovalException:
    def require(self, *, actor: ActorContext, owner_unit_id: str, reason: str) -> None:
        raise FaqAuthorizationError(
            "self approval is disabled without a configured POC-only exception policy"
        )


class PocOnlySelfApprovalException:
    """An explicit non-production exception, guarded by its own capability."""

    def __init__(self, authorization: FaqAuthorizationPort, *, environment: str) -> None:
        self._authorization = authorization
        self._environment = environment

    def require(self, *, actor: ActorContext, owner_unit_id: str, reason: str) -> None:
        if self._environment != "poc" or not reason.strip():
            raise FaqAuthorizationError(
                "self approval is permitted only in POC with a recorded reason"
            )
        self._authorization.require(
            actor=actor, capability="ops.faq.poc_self_approve", owner_unit_id=owner_unit_id
        )
