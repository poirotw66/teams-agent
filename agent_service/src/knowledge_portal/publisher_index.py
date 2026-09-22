"""Index artifact construction for knowledge release builds."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

from knowledge_core.document_models import DocumentChunk
from knowledge_core.layout_source_chunks import load_source_chunks_with_layout
from knowledge_portal.ports.retrieval import get_hybrid_index_factory

from .models import KnowledgeVersionRecord, ReleaseManifestEntry
from .settings import PortalSettings

logger = logging.getLogger(__name__)


def write_parent_artifact(release_dir: Path, chunks: list[DocumentChunk]) -> None:
    parents: dict[str, dict[str, object]] = {}
    for chunk in chunks:
        parent_id = chunk.parent_id
        if not parent_id:
            continue
        parent = parents.setdefault(
            parent_id,
            {
                "parentId": parent_id,
                "chunkIds": [],
                "sourcePath": chunk.source_path,
                "pageStart": chunk.page,
                "pageEnd": chunk.page_end,
            },
        )
        parent["chunkIds"].append(chunk.chunk_id)
    path = release_dir / "index" / "parents.json"
    path.write_text(
        json.dumps({"schemaVersion": 1, "parents": list(parents.values())}, indent=2),
        encoding="utf-8",
    )


def write_file_search_artifact(
    release_dir: Path,
    chunks: list[DocumentChunk],
    *,
    environment: str,
) -> None:
    staging_dir = release_dir / "file-search"
    staging_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for chunk in chunks:
        chunk_id = chunk.chunk_id
        slug = f"{chunk_id}.md"
        (staging_dir / slug).write_text(chunk.content, encoding="utf-8")
        entries.append(
            {
                "slug": slug,
                "releaseId": chunk.release_id,
                "documentId": chunk.document_id,
                "versionId": chunk.version_id,
                "versionNumber": chunk.version_number,
                "chunkId": chunk_id,
                "sourcePath": chunk.source_path,
                "parentId": chunk.parent_id,
                "page": chunk.page,
                "allowedGroups": list(chunk.allowed_groups),
                "contentHash": chunk.content_hash,
                "sourceAliases": chunk.source_aliases,
                "contentState": chunk.content_state,
                "effectiveAt": chunk.effective_at,
                "expiresAt": chunk.expires_at,
                "applicableEnvironments": chunk.applicable_environments,
            }
        )
    (staging_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "deploymentEnvironment": environment,
                "documents": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def synchronize_file_search_if_configured(
    settings: PortalSettings,
    release_dir: Path,
) -> str | None:
    from .publisher_finalize import ReleaseBuildError

    if settings.gemini_file_search_sync_enabled:
        try:
            from .file_search_release import synchronize_file_search_release

            return synchronize_file_search_release(
                release_dir,
                api_key=settings.gemini_file_search_api_key or "",
            )
        except Exception as error:
            raise ReleaseBuildError(
                f"Gemini File Search release sync failed: {error}"
            ) from error
    if settings.require_file_search_parity:
        raise ReleaseBuildError(
            "Gemini File Search parity is required but sync is disabled."
        )
    return None


def build_release_index_from_sources(
    *,
    release_dir: Path,
    release_id: str,
    sources_dir: Path,
    published_versions: list[KnowledgeVersionRecord],
    manifest: list[ReleaseManifestEntry],
    selected_embedding: str | None,
    settings: PortalSettings,
    index_path: Path,
    previous_release: object | None = None,
) -> str | None:
    from .publisher_finalize import ReleaseBuildError
    from .incremental_embeddings import (
        apply_reused_embeddings,
        index_setting_fingerprint,
        load_previous_release_index_payload,
    )
    from .models import ReleaseRecord

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        temp_sources = temp_root / "sources"
        temp_sources.mkdir(parents=True, exist_ok=True)
        # Match the corpus layout expected by extract_images:
        # sources/*.md next to sources/assets/<slug>/.
        release_assets = release_dir / "assets"
        if release_assets.is_dir():
            shutil.copytree(release_assets, temp_sources / "assets")
        for source_file in sources_dir.glob("*.md"):
            shutil.copy2(source_file, temp_sources / source_file.name)
        version_by_document = {
            version.document_id: version for version in published_versions
        }
        ingestion_metadata = {}
        for entry in manifest:
            version = version_by_document[entry.document_id]
            ingestion_metadata[str(entry.source_path)] = {
                "documentId": entry.document_id,
                "versionId": entry.version_id,
                "versionNumber": entry.version_number,
                "releaseId": release_id,
                "allowedGroups": list(entry.acl_groups or []),
                "classification": "internal",
                "chunkingProfile": "AUTO",
                "sourceType": version.source_type,
                "sourceAliases": entry.source_aliases,
                "contentState": entry.content_state,
                "effectiveAt": entry.effective_at,
                "expiresAt": entry.expires_at,
                "applicableEnvironments": entry.applicable_environments,
            }
        (temp_root / "metadata.json").write_text(
            json.dumps(ingestion_metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        chunks = load_source_chunks_with_layout(
            temp_root,
            settings.chunk_size,
            settings.chunk_overlap,
        )
        if not chunks:
            raise ReleaseBuildError("Release build produced zero searchable segments.")

        previous = previous_release if isinstance(previous_release, ReleaseRecord) else None
        fingerprint = index_setting_fingerprint(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            embedding_model=selected_embedding,
        )
        previous_payload = load_previous_release_index_payload(settings, previous)
        apply_reused_embeddings(
            chunks,
            previous_payload=previous_payload,
            selected_embedding=selected_embedding,
            previous_release=previous,
            new_fingerprint=fingerprint,
        )

        index = get_hybrid_index_factory().create(chunks, selected_embedding)
        if selected_embedding:
            index.add_embeddings(only_missing=True)
        index.save(index_path)
        write_parent_artifact(release_dir, chunks)
        write_file_search_artifact(
            release_dir,
            chunks,
            environment=settings.deployment_environment,
        )
        return synchronize_file_search_if_configured(settings, release_dir)


def materialize_release_index(
    *,
    release_dir: Path,
    release_id: str,
    published_versions: list[KnowledgeVersionRecord],
    manifest: list[ReleaseManifestEntry],
    bundled_index_path: Path | None,
    embedding_model: str | None,
    settings: PortalSettings,
    previous_release: object | None = None,
) -> tuple[Path, str | None, str | None]:
    """Return (index_path, selected_embedding, file_search_store)."""
    index_path = release_dir / "index" / "chunks.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    selected_embedding = embedding_model or settings.embedding_model
    copy_bundled = (
        embedding_model is None
        and bundled_index_path is not None
        and bundled_index_path.is_file()
    )
    file_search_store: str | None = None
    if copy_bundled:
        shutil.copy2(bundled_index_path, index_path)
        logger.info(
            "Copied bundled knowledge index into release %s from %s",
            release_id,
            bundled_index_path,
        )
    elif not published_versions:
        index = get_hybrid_index_factory().create([], selected_embedding)
        index.save(index_path)
        logger.info("Built empty knowledge release %s with 0 chunks", release_id)
    else:
        file_search_store = build_release_index_from_sources(
            release_dir=release_dir,
            release_id=release_id,
            sources_dir=release_dir / "sources",
            published_versions=published_versions,
            manifest=manifest,
            selected_embedding=selected_embedding,
            settings=settings,
            index_path=index_path,
            previous_release=previous_release,
        )
    return index_path, selected_embedding, file_search_store


__all__ = [
    "materialize_release_index",
    "write_file_search_artifact",
    "write_parent_artifact",
]
