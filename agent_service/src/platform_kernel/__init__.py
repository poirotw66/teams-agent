"""Stable cross-domain contracts for the modular monolith.

Domain packages may depend on platform_kernel. platform_kernel must not import
agent_service, knowledge_portal, ai_ops_backoffice, or teams_agent.
"""

from __future__ import annotations

from platform_kernel.ports.governance import GovernanceProvider
from platform_kernel.ports.release_gate import (
    ReleaseGateBlockedError,
    ReleaseGateChecker,
)
from platform_kernel.ports.source_catalog import (
    SourceCatalogEntry,
    SourceCatalogWriter,
)

__all__ = [
    "GovernanceProvider",
    "ReleaseGateBlockedError",
    "ReleaseGateChecker",
    "SourceCatalogEntry",
    "SourceCatalogWriter",
]
