"""Source catalog write port used when a knowledge release becomes active."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SourceCatalogEntry:
    """Neutral source-identity record independent of Backoffice persistence models."""

    source_ref_id: str
    tenant_id: str
    document_id: str
    version_id: str
    release_id: str
    mapping_status: str
    content_hash: str = ""
    chunk_id: str | None = None
    artifact_ref: str | None = None
    source_type: str = "DERIVED_MARKDOWN"
    title: str | None = None
    source_path: str | None = None
    excerpt: str | None = None
    original_asset_name: str | None = None
    acl_groups: tuple[str, ...] = field(default_factory=tuple)


class SourceCatalogWriter(Protocol):
    async def save_entries(self, entries: Sequence[SourceCatalogEntry]) -> int:
        """Persist catalog entries. Returns the number of saved records."""
        ...
