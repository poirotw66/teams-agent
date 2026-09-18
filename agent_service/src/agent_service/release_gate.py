"""Compatibility facade for release-gate helpers.

Prefer ``knowledge_core.release_gate`` for new call sites.
"""

from __future__ import annotations

from knowledge_core.release_gate import (
    ReleaseGateBlockedError,
    ReleaseGateChecker,
    require_release_gate,
)

__all__ = [
    "ReleaseGateBlockedError",
    "ReleaseGateChecker",
    "require_release_gate",
]
