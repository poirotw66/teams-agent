from __future__ import annotations

from pathlib import Path
from typing import Any

from .migration_bootstrap import activate_bootstrap_release, import_source_versions
from .models import PortalActor, ReleaseRecord, utc_now
from .publisher import ReleasePublisher
from .rbac import require_minimum_role
from .settings import PortalSettings


class KnowledgeMigrationService:
    def __init__(
        self,
        settings: PortalSettings,
        repository,
        publisher: ReleasePublisher,
        *,
        release_gate_checker: Any | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._publisher = publisher
        self.release_gate_checker = release_gate_checker

    async def bootstrap_release_0001(
        self,
        *,
        actor: PortalActor,
        sources_dir: Path,
        correlation_id: str,
        release_id: str = "release-0001",
        change_reason: str = "Baseline import from existing Markdown corpus.",
        bundled_index_path: Path | None = None,
    ) -> ReleaseRecord:
        require_minimum_role(actor, "PLATFORM")
        if not sources_dir.is_dir():
            raise FileNotFoundError(f"Sources directory not found: {sources_dir}")

        source_files = sorted(
            path for path in sources_dir.glob("*.md") if not path.name.upper().startswith("README")
        )
        if not source_files:
            raise ValueError(f"No Markdown sources found in {sources_dir}")

        now = utc_now()
        published_versions = await import_source_versions(
            repository=self._repository,
            settings=self._settings,
            actor=actor,
            source_files=source_files,
            change_reason=change_reason,
            now=now,
        )
        return await activate_bootstrap_release(
            repository=self._repository,
            settings=self._settings,
            publisher=self._publisher,
            actor=actor,
            release_id=release_id,
            published_versions=published_versions,
            bundled_index_path=bundled_index_path,
            source_files=source_files,
            sources_dir=sources_dir,
            change_reason=change_reason,
            correlation_id=correlation_id,
            now=now,
            release_gate_checker=self.release_gate_checker,
        )

    async def sync_from_local_corpus(
        self,
        *,
        actor: PortalActor,
        sources_dir: Path,
        bundled_index_path: Path | None,
        correlation_id: str,
        release_id: str = "release-0001",
    ) -> ReleaseRecord:
        return await self.bootstrap_release_0001(
            actor=actor,
            sources_dir=sources_dir,
            correlation_id=correlation_id,
            release_id=release_id,
            change_reason="Synced portal release from local sources and bundled index.",
            bundled_index_path=bundled_index_path,
        )
