"""Release manifest writing and ReleaseRecord assembly."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from knowledge_core.artifacts import INDEX_RELATIVE_PATH
from knowledge_core.release_artifacts import (
    KnowledgeReleaseValidationError,
    inspect_index_artifact,
    validate_release_artifacts,
)
from knowledge_core.target_manifest import knowledge_release_target_manifest_hash
from knowledge_portal.acl_artifact import write_acl_artifact
from knowledge_portal.incremental_embeddings import index_setting_fingerprint
from knowledge_portal.ports.release_publish import (
    PublishedReleaseInfo,
    get_release_directory_publisher,
)
from knowledge_portal.service_catalog_artifact import write_service_catalog_artifact
from knowledge_portal.service_catalog_draft_store import build_catalog_draft_store
from knowledge_portal.service_catalog_governance import load_approved_catalog_for_release

from .models import ReleaseManifestEntry, ReleaseRecord, utc_now
from .settings import PortalSettings


class ReleaseBuildError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def _require_vertex_index_provenance(release_dir: Path) -> None:
    from agent_service.gemini_backend import GeminiApiBackend, peek_gemini_api_backend

    if peek_gemini_api_backend() is not GeminiApiBackend.VERTEX_AI:
        return
    artifact = inspect_index_artifact(release_dir / INDEX_RELATIVE_PATH)
    if (
        artifact.embedding_backend != GeminiApiBackend.VERTEX_AI.value
        or not artifact.embedding_vertex_location
    ):
        raise ReleaseBuildError(
            "VERTEX_AI production releases must record embeddingBackend=VERTEX_AI "
            "and embeddingVertexLocation. Rebuild the index; do not reuse a "
            "Developer API release by model ID."
        )


def publish_release_if_configured(
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


def write_release_manifest_file(
    *,
    release_dir: Path,
    release_id: str,
    settings: PortalSettings,
    created_by: str,
    created_at: datetime,
    corpus_hash: str,
    manifest: list[ReleaseManifestEntry],
    resolved_tenant_id: str,
    index_artifact: object,
    file_search_store: str | None,
) -> Path:
    manifest_path = release_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseId": release_id,
                "purpose": settings.release_purpose,
                "deploymentEnvironment": settings.deployment_environment,
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
    return manifest_path


def validate_production_release_if_needed(
    settings: PortalSettings,
    *,
    release_id: str,
    resolved_tenant_id: str,
) -> None:
    if not (
        settings.release_gcs_bucket and settings.release_purpose == "PRODUCTION"
    ):
        return
    try:
        validate_release_artifacts(
            settings.release_artifact_dir,
            release_id,
            require_vectors=True,
            expected_tenant_id=resolved_tenant_id,
            expected_purpose="PRODUCTION",
        )
        _require_vertex_index_provenance(settings.release_artifact_dir / release_id)
    except KnowledgeReleaseValidationError as error:
        raise ReleaseBuildError(
            f"Production release validation failed: {error}"
        ) from error


def require_approved_catalog_for_production_if_needed(
    settings: PortalSettings,
    *,
    governed_catalog: dict | None,
) -> None:
    """Fail PRODUCTION finalize when an APPROVED catalog draft is required."""
    if settings.release_purpose != "PRODUCTION":
        return
    required = bool(settings.require_approved_catalog_for_production)
    if not required and bool(settings.require_dual_approval):
        # Enterprise dual-approval mode implies governed catalog for PRODUCTION.
        required = not settings.effective_relaxed_workflow()
    if not required:
        return
    if governed_catalog is None:
        raise ReleaseBuildError(
            "PRODUCTION finalize requires an APPROVED service catalog draft. "
            "Approve the catalog via /api/catalog/approve, or set "
            "KNOWLEDGE_PORTAL_REQUIRE_APPROVED_CATALOG=false for local opt-out."
        )


def assemble_release_record(
    *,
    settings: PortalSettings,
    release_id: str,
    created_by: str,
    previous_release_id: str | None,
    manifest: list[ReleaseManifestEntry],
    corpus_hash: str,
    index_path: Path,
    selected_embedding: str | None,
    resolved_tenant_id: str,
    created_at: datetime,
    file_search_store: str | None,
    published_release: PublishedReleaseInfo | None,
) -> ReleaseRecord:
    index_artifact = inspect_index_artifact(index_path)
    return ReleaseRecord(
        release_id=release_id,
        status="READY",
        purpose=settings.release_purpose,
        manifest=manifest,
        corpus_hash=corpus_hash,
        target_manifest_hash=knowledge_release_target_manifest_hash(
            release_id=release_id
        ),
        index_artifact_uri=str(index_path),
        index_setting_version=index_setting_fingerprint(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            embedding_model=selected_embedding,
            embedding_backend=index_artifact.embedding_backend,
            embedding_vertex_location=index_artifact.embedding_vertex_location,
            embedding_dimensions=index_artifact.embedding_dimensions,
        ),
        created_at=created_at,
        previous_release_id=previous_release_id,
        created_by=created_by,
        tenant_id=resolved_tenant_id,
        artifact_bucket=(
            published_release.bucket if published_release is not None else None
        ),
        artifact_object_prefix=(
            published_release.object_prefix if published_release is not None else None
        ),
        manifest_generation=(
            published_release.manifest_generation
            if published_release is not None
            else None
        ),
        index_generation=(
            published_release.index_generation if published_release is not None else None
        ),
        index_sha256=index_artifact.sha256,
        chunk_count=index_artifact.chunk_count,
        vector_count=index_artifact.vector_count,
        embedding_model=index_artifact.embedding_model,
        embedding_dimensions=index_artifact.embedding_dimensions,
        embedding_backend=index_artifact.embedding_backend,
        embedding_vertex_location=index_artifact.embedding_vertex_location,
        file_search_store=file_search_store,
        hybrid_backend_ready=True,
        file_search_backend_ready=file_search_store is not None,
    )


def finalize_release_artifacts(
    *,
    settings: PortalSettings,
    release_dir: Path,
    release_id: str,
    created_by: str,
    previous_release_id: str | None,
    manifest: list[ReleaseManifestEntry],
    corpus_hash: str,
    index_path: Path,
    selected_embedding: str | None,
    tenant_id: str | None,
    file_search_store: str | None,
) -> ReleaseRecord:
    index_artifact = inspect_index_artifact(index_path)
    resolved_tenant_id = tenant_id or settings.default_tenant_id
    created_at = utc_now()
    write_release_manifest_file(
        release_dir=release_dir,
        release_id=release_id,
        settings=settings,
        created_by=created_by,
        created_at=created_at,
        corpus_hash=corpus_hash,
        manifest=manifest,
        resolved_tenant_id=resolved_tenant_id,
        index_artifact=index_artifact,
        file_search_store=file_search_store,
    )
    published_document_ids = {
        entry.document_id for entry in manifest if entry.document_id
    }
    governed_catalog = load_approved_catalog_for_release(
        settings.data_dir,
        tenant_id=resolved_tenant_id,
        release_id=release_id,
        published_document_ids=published_document_ids,
        store=build_catalog_draft_store(settings),
    )
    require_approved_catalog_for_production_if_needed(
        settings,
        governed_catalog=governed_catalog,
    )
    write_service_catalog_artifact(
        release_dir,
        release_id=release_id,
        tenant_id=resolved_tenant_id,
        manifest=manifest,
        governed_payload=governed_catalog,
    )
    write_acl_artifact(
        release_dir,
        release_id=release_id,
        tenant_id=resolved_tenant_id,
        manifest=manifest,
    )
    catalog_path = release_dir / "catalog" / "service_catalog.json"
    acl_path = release_dir / "acl" / "document_acl.json"
    if not catalog_path.is_file():
        raise ReleaseBuildError(
            f"Release '{release_id}' is missing catalog/service_catalog.json "
            "before GCS publish."
        )
    if not acl_path.is_file():
        raise ReleaseBuildError(
            f"Release '{release_id}' is missing acl/document_acl.json "
            "before GCS publish."
        )
    validate_production_release_if_needed(
        settings,
        release_id=release_id,
        resolved_tenant_id=resolved_tenant_id,
    )
    published_release = publish_release_if_configured(
        settings,
        release_dir=release_dir,
        tenant_id=resolved_tenant_id,
        release_id=release_id,
    )
    return assemble_release_record(
        settings=settings,
        release_id=release_id,
        created_by=created_by,
        previous_release_id=previous_release_id,
        manifest=manifest,
        corpus_hash=corpus_hash,
        index_path=index_path,
        selected_embedding=selected_embedding,
        resolved_tenant_id=resolved_tenant_id,
        created_at=created_at,
        file_search_store=file_search_store,
        published_release=published_release,
    )


__all__ = [
    "ReleaseBuildError",
    "assemble_release_record",
    "finalize_release_artifacts",
    "publish_release_if_configured",
    "require_approved_catalog_for_production_if_needed",
]
