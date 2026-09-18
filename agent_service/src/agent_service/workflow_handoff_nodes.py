"""Workflow node implementations for the handoff subgraph.

Public surface stays on ``HandoffWorkflowMixin`` for graph wiring. Behavior is
split across sibling ops modules by node family.
"""

from __future__ import annotations

from .workflow_handoff_route_ops import HandoffRouteOps

__all__ = ["HandoffWorkflowMixin"]


class HandoffWorkflowMixin(HandoffRouteOps):
    """LangGraph nodes owned by the handoff subgraph."""
