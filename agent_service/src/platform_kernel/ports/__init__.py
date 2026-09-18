"""Cross-domain ports."""

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
