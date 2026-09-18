"""Shared knowledge contracts for Portal, Agent, and Backoffice.

This package holds stable hashing, front-matter, release-gate, artifact-path,
release-pointer, source-identity, eligibility, and chunking-profile helpers so
Knowledge Portal (and later Backoffice) do not need to import Agent runtime
implementation modules for those concerns.
"""

from __future__ import annotations

from knowledge_core.artifacts import INDEX_RELATIVE_PATH, MANIFEST_FILENAME
from knowledge_core.chunking_profile import ChunkingProfile
from knowledge_core.eligibility import (
    ACTIVE_CONTENT_STATE,
    is_generation_metadata_eligible,
)
from knowledge_core.front_matter import parse_front_matter, strip_excluded_markdown
from knowledge_core.release_gate import (
    ReleaseGateBlockedError,
    ReleaseGateChecker,
    require_release_gate,
)
from knowledge_core.release_pointer import (
    ACTIVE_RELEASE_FILENAME,
    read_active_release_id,
    release_index_path,
    write_active_release_pointer,
)
from knowledge_core.source_identity import (
    make_source_ref_id,
    safe_source_path,
    source_path_stem,
)
from knowledge_core.target_manifest import (
    calculate_target_manifest_hash,
    faq_version_gate_manifest,
    faq_version_target_manifest_hash,
    knowledge_release_gate_manifest,
    knowledge_release_target_manifest_hash,
)

__all__ = [
    "ACTIVE_CONTENT_STATE",
    "ACTIVE_RELEASE_FILENAME",
    "INDEX_RELATIVE_PATH",
    "MANIFEST_FILENAME",
    "ChunkingProfile",
    "ReleaseGateBlockedError",
    "ReleaseGateChecker",
    "calculate_target_manifest_hash",
    "faq_version_gate_manifest",
    "faq_version_target_manifest_hash",
    "is_generation_metadata_eligible",
    "knowledge_release_gate_manifest",
    "knowledge_release_target_manifest_hash",
    "make_source_ref_id",
    "parse_front_matter",
    "read_active_release_id",
    "release_index_path",
    "require_release_gate",
    "safe_source_path",
    "source_path_stem",
    "strip_excluded_markdown",
    "write_active_release_pointer",
]
