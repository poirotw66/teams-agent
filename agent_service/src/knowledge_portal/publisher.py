from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from pathlib import Path

from agent_service.documents import load_source_chunks
from agent_service.retrieval import HybridIndex

from .draft_assets import DraftAssetStore
from .models import KnowledgeVersionRecord, ReleaseManifestEntry, ReleaseRecord, utc_now
from .settings import PortalSettings
from .validation import build_front_matter_markdown, content_hash

logger = logging.getLogger(__name__)


class ReleaseBuildError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


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
    ) -> ReleaseRecord:
        if not published_versions:
            raise ReleaseBuildError("Cannot publish an empty knowledge release.")

        self._settings.release_artifact_dir.mkdir(parents=True, exist_ok=True)
        release_dir = self._settings.release_artifact_dir / release_id
        if release_dir.exists():
            shutil.rmtree(release_dir)
        release_dir.mkdir(parents=True, exist_ok=True)
        sources_dir = release_dir / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        manifest: list[ReleaseManifestEntry] = []
        asset_store = DraftAssetStore(self._settings)
        for version in published_versions:
            filename = f"{version.document_id}.md"
            body = version.canonical_content
            if not body.lstrip().startswith("---"):
                body = build_front_matter_markdown(
                    title=version.title,
                    owner_unit_id=version.owner_unit_id,
                    effective_at=version.effective_at,
                    review_due_at=version.review_due_at,
                    audience_type=version.audience_type,
                    audience_group_ids=version.audience_group_ids,
                    version_number=version.version_number,
                    body=body,
                )
            target = sources_dir / filename
            target.write_text(body, encoding="utf-8")
            asset_store.copy_assets_to_release(release_dir, version=version)
            manifest.append(
                ReleaseManifestEntry(
                    document_id=version.document_id,
                    version_id=version.version_id,
                    title=version.title,
                    content_hash=version.content_hash,
                )
            )

        corpus_hash = hashlib.sha256(
            json.dumps(
                [entry.model_dump(mode="json") for entry in manifest],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        index_path = release_dir / "index" / "chunks.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        if bundled_index_path is not None and bundled_index_path.is_file():
            shutil.copy2(bundled_index_path, index_path)
            logger.info(
                "Copied bundled knowledge index into release %s from %s",
                release_id,
                bundled_index_path,
            )
        else:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_root = Path(temp_dir)
                temp_sources = temp_root / "sources"
                temp_sources.mkdir(parents=True, exist_ok=True)
                temp_assets = temp_root / "assets"
                release_assets = release_dir / "assets"
                if release_assets.is_dir():
                    shutil.copytree(release_assets, temp_assets)
                for source_file in sources_dir.glob("*.md"):
                    shutil.copy2(source_file, temp_sources / source_file.name)
                chunks = load_source_chunks(
                    temp_root,
                    self._settings.chunk_size,
                    self._settings.chunk_overlap,
                )
                if not chunks:
                    raise ReleaseBuildError("Release build produced zero searchable segments.")
                index = HybridIndex(chunks, self._settings.embedding_model)
                if self._settings.embedding_model:
                    index.add_embeddings()
                index.save(index_path)

        manifest_path = release_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "releaseId": release_id,
                    "corpusHash": corpus_hash,
                    "documents": [entry.model_dump(mode="json") for entry in manifest],
                    "indexArtifact": str(index_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return ReleaseRecord(
            release_id=release_id,
            status="READY",
            manifest=manifest,
            corpus_hash=corpus_hash,
            index_artifact_uri=str(index_path),
            index_setting_version=(
                f"chunk={self._settings.chunk_size};overlap={self._settings.chunk_overlap};"
                f"embedding={self._settings.embedding_model or 'bm25-only'}"
            ),
            created_at=utc_now(),
            previous_release_id=previous_release_id,
            created_by=created_by,
        )
