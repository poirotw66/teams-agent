"""Shared route context for console handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConsoleRouteContext:
    """Collaborators and auth hooks shared by console route modules."""

    current_actor: Callable[..., Any]
    require_capability: Callable[..., Any]
    quality_service: Any = None
    knowledge_client: Any = None
    evaluation_service: Any = None
    evaluation_run_service: Any = None
    quality_gate_service: Any = None
