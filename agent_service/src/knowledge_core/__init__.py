"""Shared knowledge contracts for Portal, Agent, and Backoffice.

This package holds stable hashing, front-matter, release-gate, and artifact-path
helpers so Knowledge Portal (and later Backoffice) do not need to import Agent
runtime implementation modules for those concerns.
"""

from __future__ import annotations

from knowledge_core.artifacts import INDEX_RELATIVE_PATH, MANIFEST_FILENAME
from knowledge_core.front_matter import parse_front_matter, strip_excluded_markdown
from knowledge_core.release_gate import (
    ReleaseGateBlockedError,
    ReleaseGateChecker,
    require_release_gate,
)
from knowledge_core.target_manifest import (
    calculate_target_manifest_hash,
    faq_version_gate_manifest,
    faq_version_target_manifest_hash,
    knowledge_release_gate_manifest,
    knowledge_release_target_manifest_hash,
)

__all__ = [
    "INDEX_RELATIVE_PATH",
    "MANIFEST_FILENAME",
    "ReleaseGateBlockedError",
    "ReleaseGateChecker",
    "calculate_target_manifest_hash",
    "faq_version_gate_manifest",
    "faq_version_target_manifest_hash",
    "knowledge_release_gate_manifest",
    "knowledge_release_target_manifest_hash",
    "parse_front_matter",
    "require_release_gate",
    "strip_excluded_markdown",
]
