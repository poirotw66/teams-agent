"""Shared authorization helper for quality domain use-case ops."""

from __future__ import annotations

from operations_core.access import ActorContext

from ..faq_domain.errors import FaqAuthorizationError

__all__ = ["authorize"]


def authorize(actor: ActorContext, capability: str, owner_unit_id: str) -> None:
    if not actor.has_capability(capability) or not actor.allows_owner_unit(owner_unit_id):
        raise FaqAuthorizationError("quality operation is outside actor capability or scope")
