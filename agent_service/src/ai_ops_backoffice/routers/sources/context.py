"""Shared route context for source citation and file routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourcesRouteContext:
    """Collaborators and auth hooks shared by sources route modules."""

    query_service: Any
    current_actor: Callable[..., Any]
    require_capability: Callable[[Any, str], None]
    audit_read: Callable[..., Any]
