"""Shared route context for FAQ lifecycle handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FaqRouteContext:
    """Collaborators and auth hooks shared by FAQ route modules."""

    resolved_settings: Any
    query_service: Any
    faq_service: Any
    quality_service: Any
    quality_metrics_by_issue: Callable[..., Any]
    current_actor: Callable[..., Any]
    require_capability: Callable[..., Any]
    audit_read: Callable[..., Any]
