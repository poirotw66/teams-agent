"""Shared route context for quality handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityRouteContext:
    """Collaborators and auth hooks shared by quality route modules."""

    resolved_settings: Any
    query_service: Any
    quality_service: Any
    faq_service: Any
    knowledge_client: Any
    quality_metrics_by_issue: Callable[..., Any]
    enrich_quality_issue_display: Callable[[dict[str, Any]], dict[str, Any]]
    current_actor: Callable[..., Any]
    require_capability: Callable[[Any, str], None]
    evaluation_service: Any = None
    evaluation_run_service: Any = None
    quality_gate_service: Any = None
