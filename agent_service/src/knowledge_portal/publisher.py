from __future__ import annotations

import shutil
from pathlib import Path

from .models import KnowledgeVersionRecord, ReleaseRecord
from .publisher_finalize import ReleaseBuildError, finalize_release_artifacts
from .publisher_index import materialize_release_index
from .publisher_sources import (
    corpus_hash_for_manifest,
    filter_eligible_versions,
    write_release_sources,
)
from .settings import PortalSettings

__all__ = ["ReleaseBuildError", "ReleasePublisher"]


class ReleasePublisher:
    def __init__(self, settings: PortalSettings) -> None:
        self._settings = settings

    def build_release(
        self,
        *,
        release_id: str,
        published_versions: list[KnowledgeVersionRecord],
        created_by: str,
        previous_release_id: str | None,
        bundled_index_path: Path | None = None,
        embedding_model: str | None = None,
        tenant_id: str | None = None,
        previous_release: ReleaseRecord | None = None,
    ) -> ReleaseRecord:
        self._settings.release_artifact_dir.mkdir(parents=True, exist_ok=True)
        release_dir = self._settings.release_artifact_dir / release_id
        if release_dir.exists():
            shutil.rmtree(release_dir)
        release_dir.mkdir(parents=True, exist_ok=True)
        published_versions = filter_eligible_versions(
            published_versions,
            environment=self._settings.deployment_environment,
        )
        manifest = write_release_sources(
            release_dir=release_dir,
            published_versions=published_versions,
            settings=self._settings,
        )
        corpus_hash = corpus_hash_for_manifest(manifest)
        index_path, selected_embedding, file_search_store = materialize_release_index(
            release_dir=release_dir,
            release_id=release_id,
            published_versions=published_versions,
            manifest=manifest,
            bundled_index_path=bundled_index_path,
            embedding_model=embedding_model,
            settings=self._settings,
            previous_release=previous_release,
        )
        return finalize_release_artifacts(
            settings=self._settings,
            release_dir=release_dir,
            release_id=release_id,
            created_by=created_by,
            previous_release_id=previous_release_id,
            manifest=manifest,
            corpus_hash=corpus_hash,
            index_path=index_path,
            selected_embedding=selected_embedding,
            tenant_id=tenant_id,
            file_search_store=file_search_store,
        )
