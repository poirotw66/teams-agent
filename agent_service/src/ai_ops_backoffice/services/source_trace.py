"""Resolve answer citations to a release-scoped, authorized source preview.

Provides direct O(1) repository queries, bounded LRU/TTL caching, strict historical
version matching without fallbacks, and multi-format locators (F02, F03, F08, A06).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from knowledge_core.artifact_ports import ArtifactStorage
from knowledge_core.source_resolution import ResolvedSource

from .source_models import SourceLocator, SourceRecord
from .source_repository import (
    BoundedSourceCache,
    InMemorySourceRecordRepository,
    SourceRecordRepository,
)
from .source_trace_locator import build_locator, match_chunk
from .source_trace_mapping import resolved_to_source_record, source_record_to_resolved
from .source_trace_payload import (
    preview_payload as build_preview_payload,
)
from .source_trace_payload import (
    reference_payload as build_reference_payload,
)
from .source_trace_payload import (
    references_for_events as collect_references_for_events,
)
from .source_trace_release import ReleaseLoad, list_release_ids, load_release
from .source_trace_release import (
    active_release_id as read_active_release_id,
)
from .source_trace_resolve import (
    resolve_citation as resolve_citation_from_releases,
)
from .source_trace_resolve import (
    resolve_source_ref as resolve_source_ref_from_store,
)

__all__ = ["SourceTraceResolver"]


class SourceTraceResolver:
    """Read-only resolver over private release artifacts and direct SourceRecord repository.

    The resolver never exposes filesystem paths directly. It provides direct O(1) lookups
    via bounded cache and repository, avoiding release scans on direct citations.
    """

    def __init__(
        self,
        releases_dir: Path,
        source_repository: SourceRecordRepository | None = None,
        cache: BoundedSourceCache | None = None,
        artifact_storage: ArtifactStorage | None = None,
    ) -> None:
        self.releases_dir = releases_dir.expanduser().resolve()
        self.source_repository = source_repository or InMemorySourceRecordRepository()
        self.cache = cache or BoundedSourceCache(max_size=500, ttl_seconds=300.0)
        self.artifact_storage = artifact_storage
        self._release_cache: dict[str, tuple[int, int, ReleaseLoad]] = {}

    def active_release_id(self) -> str | None:
        return read_active_release_id(self.releases_dir)

    def _release_ids(self, preferred: str | None = None) -> list[str]:
        return list_release_ids(self.releases_dir, preferred)

    def _load_release(
        self, release_id: str
    ) -> (
        tuple[
            Path, list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]
        ]
        | None
    ):
        return load_release(self.releases_dir, release_id, self._release_cache)

    @staticmethod
    def _match_chunk(
        chunks: list[dict[str, Any]],
        citation: dict[str, Any],
    ) -> dict[str, Any] | None:
        return match_chunk(chunks, citation)

    @staticmethod
    def _build_locator(
        source_type: str,
        chunk: dict[str, Any],
        entry: dict[str, Any],
        citation: dict[str, Any],
    ) -> SourceLocator:
        return build_locator(source_type, chunk, entry, citation)

    def _source_record_to_resolved(self, rec: SourceRecord) -> ResolvedSource:
        return source_record_to_resolved(rec)

    def _resolved_to_source_record(
        self, resolved: ResolvedSource, *, tenant_id: str
    ) -> SourceRecord:
        return resolved_to_source_record(resolved, tenant_id=tenant_id)

    def resolve_citation(
        self,
        citation: dict[str, Any],
        *,
        fallback_release_id: str | None = None,
        tenant_id: str = "default",
    ) -> ResolvedSource | None:
        return resolve_citation_from_releases(
            releases_dir=self.releases_dir,
            release_cache=self._release_cache,
            citation=citation,
            fallback_release_id=fallback_release_id,
            tenant_id=tenant_id,
        )

    def resolve_source_ref(
        self,
        source_ref_id: str,
        *,
        tenant_id: str = "default",
    ) -> ResolvedSource | None:
        """Resolve a source reference directly using O(1) bounded cache and repository.

        Avoids scanning all release directories unless querying legacy unindexed releases.
        """
        return resolve_source_ref_from_store(
            releases_dir=self.releases_dir,
            release_cache=self._release_cache,
            source_repository=self.source_repository,
            cache=self.cache,
            source_ref_id=source_ref_id,
            tenant_id=tenant_id,
        )

    def references_for_events(self, events: Iterable[Any]) -> list[dict[str, Any]]:
        return collect_references_for_events(
            releases_dir=self.releases_dir,
            release_cache=self._release_cache,
            events=events,
        )

    @staticmethod
    def reference_payload(source: ResolvedSource) -> dict[str, Any]:
        return build_reference_payload(source)

    def preview_payload(self, source: ResolvedSource) -> dict[str, Any]:
        return build_preview_payload(source)
