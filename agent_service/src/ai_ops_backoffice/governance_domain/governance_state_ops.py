"""Shared governance state mutation and authorization predicates."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext


def _allowed(actor: ActorContext, capability: str, requested: str | None, actual: str) -> bool:
    if requested not in {None, actual}:
        return False
    return actor.has_capability(capability)


def _upsert(items: tuple[Any, ...], item: Any, key: str) -> tuple[Any, ...]:
    identifier = getattr(item, key)
    kept = tuple(existing for existing in items if getattr(existing, key) != identifier)
    return (*kept, item)
