"""Shared route context for quality-gate handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from operations_core.access import ActorContext

from ...evaluation_domain.gate_service import QualityGateService


@dataclass(frozen=True)
class GateRouteContext:
    """Collaborators and auth hooks shared by gate route modules."""

    gate_service: QualityGateService
    current_actor: Callable[..., ActorContext]
    require_capability: Callable[[ActorContext, str], None]
