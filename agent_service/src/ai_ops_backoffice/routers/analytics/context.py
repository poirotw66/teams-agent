"""Shared route context for analytics handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnalyticsRouteContext:
    """Collaborators and auth hooks shared by analytics route modules."""

    resolved_settings: Any
    query_service: Any
    governance_service: Any
    current_actor: Callable[..., Any]
    require_capability: Callable[[Any, str], None]
    audit_read: Callable[..., Any]
    export_rate_limiter: Any
    example_service: Any = None
    quality_service: Any = None
    sync_service: Any = None
    budget_service: Any = None
