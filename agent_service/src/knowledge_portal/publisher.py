from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from pathlib import Path

from knowledge_core.artifacts import INDEX_RELATIVE_PATH
from knowledge_core.document_models import DocumentChunk
from knowledge_core.eligibility import is_generation_metadata_eligible
from knowledge_core.layout_source_chunks import load_source_chunks_with_layout
from knowledge_core.release_artifacts import (
    KnowledgeReleaseValidationError,
    inspect_index_artifact,
    validate_release_artifacts,
)
from knowledge_core.target_manifest import knowledge_release_target_manifest_hash
from knowledge_portal.ports.release_publish import (
    PublishedReleaseInfo,
    get_release_directory_publisher,
)
from knowledge_portal.ports.retrieval import get_hybrid_index_factory

from .draft_assets import DraftAssetStore
from .models import KnowledgeVersionRecord, ReleaseManifestEntry, ReleaseRecord, utc_now
from .original_assets import OriginalAssetStore
from .settings import PortalSettings
from .validation import build_front_matter_markdown

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
        embedding_model: str | None = None,
        tenant_id: str | None = None,
    ) -> ReleaseRecord:
        self._settings.release_artifact_dir.mkdir(parents=True, exist_ok=True)
        release_dir = self._settings.release_artifact_dir / release_id
        if release_dir.exists():
            shutil.rmtree(release_dir)
        release_dir.mkdir(parents=True, exist_ok=True)
        sources_dir = release_dir / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        published_versions = [
            version
            for version in published_versions
            if is_generation_metadata_eligible(
                content_state=version.content_state,
                effective_at=version.effective_at,
                expires_at=version.expires_at,
                applicable_environments=version.applicable_environments,
                environment=self._settings.deployment_environment,
            )
        ]
        manifest: list[ReleaseManifestEntry] = []
        asset_store = DraftAssetStore(self._settings)
        original_store = OriginalAssetStore(self._settings)
        if published_versions:
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
                original_available = original_store.copy_to_release(
                    release_dir,
                    version=version,
                )
                version_acl = (
                    ["grp_public"]
                    if version.audience_type == "ALL_EMPLOYEES"
                    else [str(g).strip() for g in version.audience_group_ids if str(g).strip()]
                    or ["grp_restricted"]
                )
                manifest.append(
                    ReleaseManifestEntry(
                        document_id=version.document_id,
                        version_id=version.version_id,
                        version_number=version.version_number,
                        title=version.title,
                        content_hash=version.content_hash,
                        source_path=f"sources/{filename}",
                        source_type=version.source_type,
                        original_asset_available=original_available,
                        original_asset_name=(
                            version.original_asset_name if original_available else None
                        ),
                        artifact_ref=getattr(version, "original_artifact_ref", None),
                        acl_groups=version_acl,
                        source_aliases=version.source_aliases,
                        content_state=version.content_state,
                        effective_at=version.effective_at,
                        expires_at=version.expires_at,
                        applicable_environments=version.applicable_environments,
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
        selected_embedding = embedding_model or self._settings.embedding_model
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
                    self._settings.chunk_size,
                    self._settings.chunk_overlap,
                )
                if not chunks:
                    raise ReleaseBuildError("Release build produced zero searchable segments.")
                index = get_hybrid_index_factory().create(chunks, selected_embedding)
                if selected_embedding:
                    index.add_embeddings()
                index.save(index_path)
                _write_parent_artifact(release_dir, chunks)
                _write_file_search_artifact(
                    release_dir,
                    chunks,
                    environment=self._settings.deployment_environment,
                )
                if self._settings.gemini_file_search_sync_enabled:
                    try:
                        from .file_search_release import (
                            synchronize_file_search_release,
                        )

                        file_search_store = synchronize_file_search_release(
                            release_dir,
                            api_key=self._settings.gemini_file_search_api_key or "",
                        )
                    except Exception as error:
                        raise ReleaseBuildError(
                            f"Gemini File Search release sync failed: {error}"
                        ) from error
                elif self._settings.require_file_search_parity:
                    raise ReleaseBuildError(
                        "Gemini File Search parity is required but sync is disabled."
                    )

        index_artifact = inspect_index_artifact(index_path)
        resolved_tenant_id = tenant_id or self._settings.default_tenant_id
        created_at = utc_now()
        manifest_path = release_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "releaseId": release_id,
                    "purpose": self._settings.release_purpose,
                    "deploymentEnvironment": self._settings.deployment_environment,
                    "tenantId": resolved_tenant_id,
                    "createdAt": created_at.isoformat(),
                    "createdBy": created_by,
                    "corpusHash": corpus_hash,
                    "documents": [entry.model_dump(mode="json") for entry in manifest],
                    "sourceMap": [entry.model_dump(mode="json") for entry in manifest],
                    "indexArtifact": INDEX_RELATIVE_PATH,
                    "index": index_artifact.to_manifest_dict(),
                    "backends": {
                        "hybrid": {"ready": True},
                        "geminiFileSearch": {
                            "ready": file_search_store is not None,
                            "store": file_search_store,
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if self._settings.release_gcs_bucket and self._settings.release_purpose == "PRODUCTION":
            try:
                validate_release_artifacts(
                    self._settings.release_artifact_dir,
                    release_id,
                    require_vectors=True,
                    expected_tenant_id=resolved_tenant_id,
                    expected_purpose="PRODUCTION",
                )
            except KnowledgeReleaseValidationError as error:
                raise ReleaseBuildError(f"Production release validation failed: {error}") from error

        published_release = _publish_release_if_configured(
            self._settings,
            release_dir=release_dir,
            tenant_id=resolved_tenant_id,
            release_id=release_id,
        )

        return ReleaseRecord(
            release_id=release_id,
            status="READY",
            purpose=self._settings.release_purpose,
            manifest=manifest,
            corpus_hash=corpus_hash,
            target_manifest_hash=knowledge_release_target_manifest_hash(release_id=release_id),
            index_artifact_uri=str(index_path),
            index_setting_version=(
                f"chunk={self._settings.chunk_size};overlap={self._settings.chunk_overlap};"
                f"embedding={selected_embedding or 'bm25-only'}"
            ),
            created_at=created_at,
            previous_release_id=previous_release_id,
            created_by=created_by,
            tenant_id=resolved_tenant_id,
            artifact_bucket=(published_release.bucket if published_release is not None else None),
            artifact_object_prefix=(
                published_release.object_prefix if published_release is not None else None
            ),
            manifest_generation=(
                published_release.manifest_generation if published_release is not None else None
            ),
            index_generation=(
                published_release.index_generation if published_release is not None else None
            ),
            index_sha256=index_artifact.sha256,
            chunk_count=index_artifact.chunk_count,
            vector_count=index_artifact.vector_count,
            embedding_model=index_artifact.embedding_model,
            embedding_dimensions=index_artifact.embedding_dimensions,
            file_search_store=file_search_store,
            hybrid_backend_ready=True,
            file_search_backend_ready=file_search_store is not None,
        )


def _publish_release_if_configured(
    settings: PortalSettings,
    *,
    release_dir: Path,
    tenant_id: str,
    release_id: str,
) -> PublishedReleaseInfo | None:
    if not settings.release_gcs_bucket:
        return None
    publisher = get_release_directory_publisher()
    if publisher is None:
        raise ReleaseBuildError(
            "Release GCS bucket is configured but no release directory "
            "publisher was wired through composition."
        )
    return publisher.publish(
        release_dir,
        bucket_name=settings.release_gcs_bucket,
        object_prefix=settings.release_gcs_prefix,
        tenant_id=tenant_id,
        release_id=release_id,
    )


def _write_parent_artifact(release_dir: Path, chunks: list[DocumentChunk]) -> None:
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


def _write_file_search_artifact(
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
        (staging_dir / slug).write_text(
            chunk.content,
            encoding="utf-8",
        )
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
